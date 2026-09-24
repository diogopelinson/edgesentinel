"""
Ciclo de incidente de ponta a ponta: engine + SQLiteEventStore reais.

Cobre o que os fakes não alcançam — o invariante de um incidente aberto
por regra vindo do banco, e o ciclo sobrevivendo ao restart do agente.
"""
import time
from unittest.mock import MagicMock

import pytest

from adapters.store.sqlite import SQLiteEventStore
from application.engine import RuleEngine
from core.entities import SensorReading
from core.incidents import IncidentState
from core.ports import ActionPort
from core.rules import Condition, Rule, Severity


def rule() -> Rule:
    # dispara acima de 80 °C, resolve em 72 (80 menos 10%)
    return Rule(
        name="temperatura_critica",
        condition=Condition(sensor_id="cpu_temp", operator=">", threshold=80.0),
        action_ids=["log"],
        severity=Severity.CRITICAL,
    )


def reading(value: float) -> SensorReading:
    return SensorReading("cpu_temp", "CPU Temperature", value, "°C")


@pytest.fixture
def store(tmp_path):
    s = SQLiteEventStore(path=tmp_path / "events.db")
    s.start()
    yield s
    s.close()


def engine_with(store, action: MagicMock | None = None) -> RuleEngine:
    return RuleEngine(
        rules=[rule()],
        actions={"log": action or MagicMock(spec=ActionPort)},
        events=store,
        incidents=store,
    )


def test_the_full_cycle_from_normal_to_resolved(store):
    action = MagicMock(spec=ActionPort)
    engine = engine_with(store, action)

    assert store.open_incidents() == []          # NORMAL: nenhum incidente

    engine.evaluate(reading(85.0))               # → TRIGGERED
    (incident,) = store.open_incidents()
    assert incident.state is IncidentState.TRIGGERED

    engine.evaluate(reading(90.0))               # agrupa no mesmo incidente
    assert len(store.open_incidents()) == 1

    store.acknowledge_incident(incident.incident_id, at=time.time())   # → ACKNOWLEDGED
    engine.evaluate(reading(92.0))
    assert action.execute.call_count == 2        # o ack parou as ações

    engine.evaluate(reading(70.0))               # → RESOLVED
    assert store.open_incidents() == []

    store.flush()
    grouped = [e for e in store.query() if e.incident_id == incident.incident_id]
    assert len(grouped) == 3                     # 85, 90 e 92 °C


def test_an_incident_keeps_grouping_after_a_restart(tmp_path):
    """
    O estado vive no banco: um agente que reinicia com a temperatura ainda
    alta continua o incidente em vez de abrir outro.
    """
    path = tmp_path / "events.db"

    first = SQLiteEventStore(path=path)
    first.start()
    engine_with(first).evaluate(reading(85.0))
    (before,) = first.open_incidents()
    first.close()

    second = SQLiteEventStore(path=path)
    second.start()
    try:
        engine_with(second).evaluate(reading(88.0))

        (after,) = second.open_incidents()
        assert after.incident_id == before.incident_id

        # o evento do disparo pós-restart aponta para o mesmo incidente: é o
        # que prova que o engine leu o estado, e não que o banco recusou um
        # segundo incidente
        second.flush()
        (latest,) = [e for e in second.query() if e.value == pytest.approx(88.0)]
        assert latest.incident_id == before.incident_id
    finally:
        second.close()


def test_an_acknowledgement_from_another_process_is_seen(tmp_path):
    """
    O `edgesentinel incidents ack` da próxima feature escreve no banco com
    o agente rodando; o agente precisa ver isso no ciclo seguinte.
    """
    path = tmp_path / "events.db"

    agent = SQLiteEventStore(path=path)
    agent.start()
    action = MagicMock(spec=ActionPort)
    engine = engine_with(agent, action)
    engine.evaluate(reading(85.0))

    cli = SQLiteEventStore(path=path)
    cli.start()
    (incident,) = cli.open_incidents()
    cli.acknowledge_incident(incident.incident_id, at=time.time())
    cli.close()

    try:
        engine.evaluate(reading(86.0))

        assert action.execute.call_count == 1
    finally:
        agent.close()


def test_a_resolved_incident_is_followed_by_a_new_one(store):
    engine = engine_with(store)

    engine.evaluate(reading(85.0))
    (first,) = store.open_incidents()
    engine.evaluate(reading(60.0))
    engine.evaluate(reading(85.0))

    (second,) = store.open_incidents()
    assert second.incident_id != first.incident_id


class TestOperatorFromTheTerminal:
    """
    O operador usa o terminal enquanto o agente roda. São dois processos sem
    canal entre eles: o único acordo é o banco, e o engine relê os incidentes
    abertos a cada avaliação. É o que estes testes provam de ponta a ponta,
    com o comando de verdade e não com o store direto.
    """

    @pytest.fixture
    def config(self, tmp_path):
        """config.yaml apontando para o mesmo banco do agente."""
        arquivo = tmp_path / "config.yaml"
        arquivo.write_text(f"""
edgesentinel:
  sensors: []
  rules: []
  actions: []
  event_store:
    path: "{(tmp_path / 'events.db').as_posix()}"
""", encoding="utf-8")
        return arquivo

    def test_acknowledging_from_the_cli_stops_the_actions_on_the_next_cycle(
        self, store, config, capsys
    ):
        from cli.incidents import run_ack

        action = MagicMock(spec=ActionPort)
        engine = engine_with(store, action)

        engine.evaluate(reading(85.0))
        (incidente,) = store.open_incidents()
        assert action.execute.call_count == 1

        assert run_ack(config, incidente.incident_id) == 0
        capsys.readouterr()

        engine.evaluate(reading(90.0))           # a regra ainda casa

        assert action.execute.call_count == 1, "a ação repetiu depois do ack"
        assert store.query(limit=10)[0].incident_id == incidente.incident_id, (
            "o disparo deixou de ir para o histórico"
        )

    def test_resolving_from_the_cli_lets_the_next_firing_open_another(
        self, store, config, capsys
    ):
        from cli.incidents import run_resolve

        engine = engine_with(store)
        engine.evaluate(reading(85.0))
        (primeiro,) = store.open_incidents()

        assert run_resolve(config, primeiro.incident_id) == 0
        capsys.readouterr()
        assert store.open_incidents() == []

        engine.evaluate(reading(86.0))
        (segundo,) = store.open_incidents()

        assert segundo.incident_id != primeiro.incident_id
        assert store.incident(primeiro.incident_id).state is IncidentState.RESOLVED

    def test_the_listing_shows_what_the_agent_opened(self, store, config, capsys):
        from cli.incidents import run_incidents

        engine = engine_with(store)
        engine.evaluate(reading(85.0))
        assert store.flush()

        assert run_incidents(config) == 0

        saida = capsys.readouterr().out
        assert "temperatura_critica" in saida
        assert "CRITICAL" in saida
