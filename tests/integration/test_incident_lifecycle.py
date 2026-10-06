"""
Incident cycle end to end: real engine + SQLiteEventStore.

Covers what the fakes cannot reach — the invariant of one incident open
per rule coming from the database, and the cycle surviving the agent's restart.
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
    # fires above 80 °C, resolves at 72 (80 minus 10%)
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

    assert store.open_incidents() == []          # NORMAL: no incident

    engine.evaluate(reading(85.0))               # → TRIGGERED
    (incident,) = store.open_incidents()
    assert incident.state is IncidentState.TRIGGERED

    engine.evaluate(reading(90.0))               # groups into the same incident
    assert len(store.open_incidents()) == 1

    store.acknowledge_incident(incident.incident_id, at=time.time())   # → ACKNOWLEDGED
    engine.evaluate(reading(92.0))
    assert action.execute.call_count == 2        # the ack stopped the actions

    engine.evaluate(reading(70.0))               # → RESOLVED
    assert store.open_incidents() == []

    store.flush()
    grouped = [e for e in store.query() if e.incident_id == incident.incident_id]
    assert len(grouped) == 3                     # 85, 90 and 92 °C


def test_an_incident_keeps_grouping_after_a_restart(tmp_path):
    """
    The state lives in the database: an agent that restarts with the temperature
    still high continues the incident instead of opening another one.
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

        # the event of the post-restart firing points to the same incident: that
        # is what proves the engine read the state, and not that the database
        # refused a second incident
        second.flush()
        (latest,) = [e for e in second.query() if e.value == pytest.approx(88.0)]
        assert latest.incident_id == before.incident_id
    finally:
        second.close()


def test_an_acknowledgement_from_another_process_is_seen(tmp_path):
    """
    The `edgesentinel incidents ack` of the next feature writes to the database
    with the agent running; the agent has to see that on the following cycle.
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
    The operator uses the terminal while the agent runs. They are two processes
    with no channel between them: the only agreement is the database, and the
    engine re-reads the open incidents on every evaluation. That is what these
    tests prove end to end, with the real command and not with the store directly.
    """

    @pytest.fixture
    def config(self, tmp_path):
        """config.yaml pointing to the same database as the agent."""
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

        engine.evaluate(reading(90.0))           # the rule still matches

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
