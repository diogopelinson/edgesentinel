import dataclasses
import sqlite3
import logging
import time
from pathlib import Path

import pytest

from unittest.mock import MagicMock
import application.engine
from core.rules import Rule, Condition, Severity
from core.entities import SensorReading, ActionContext, Event
from core.incidents import Incident, IncidentState
from core.ports import ActionPort, EventPort, IncidentPort, StatePort
from application.engine import RuleEngine


# --- helpers ---

def make_action() -> MagicMock:
    """Cria um mock de ActionPort para verificar chamadas."""
    action = MagicMock(spec=ActionPort)
    return action


def make_engine(rules: list[Rule], actions: dict) -> RuleEngine:
    return RuleEngine(rules=rules, actions=actions)


# --- fixtures locais ---

@pytest.fixture
def rule_above_75() -> Rule:
    return Rule(
        name="alta_temp",
        condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
        action_ids=["log", "webhook"],
    )


@pytest.fixture
def reading_72() -> SensorReading:
    return SensorReading(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        value=72.0,
        unit="°C",
    )


@pytest.fixture
def reading_82() -> SensorReading:
    return SensorReading(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        value=82.0,
        unit="°C",
    )


# --- testes ---

class TestRuleEngineDispatch:

    def test_executes_action_when_condition_matches(self, rule_above_75, reading_82):
        log_action = make_action()
        engine = make_engine(
            rules=[rule_above_75],
            actions={"log": log_action, "webhook": make_action()},
        )

        engine.evaluate(reading_82)

        log_action.execute.assert_called_once()

    def test_executes_all_action_ids_in_rule(self, rule_above_75, reading_82):
        log_action = make_action()
        webhook_action = make_action()
        engine = make_engine(
            rules=[rule_above_75],
            actions={"log": log_action, "webhook": webhook_action},
        )

        engine.evaluate(reading_82)

        log_action.execute.assert_called_once()
        webhook_action.execute.assert_called_once()

    def test_does_not_execute_when_condition_is_false(self, rule_above_75, reading_72):
        log_action = make_action()
        engine = make_engine(
            rules=[rule_above_75],
            actions={"log": log_action},
        )

        engine.evaluate(reading_72)

        log_action.execute.assert_not_called()

    def test_passes_correct_context_to_action(self, rule_above_75, reading_82):
        """Verifica que o ActionContext passado para a ação está correto."""
        log_action = make_action()
        engine = make_engine(
            rules=[rule_above_75],
            actions={"log": log_action},
        )

        engine.evaluate(reading_82)

        context: ActionContext = log_action.execute.call_args[0][0]
        assert context.rule_name == "alta_temp"
        assert context.reading is reading_82
        assert context.score is None

    def test_passes_score_in_context_when_provided(self, rule_above_75, reading_82, anomaly_score):
        log_action = make_action()
        engine = make_engine(
            rules=[rule_above_75],
            actions={"log": log_action},
        )

        engine.evaluate(reading_82, score=anomaly_score)

        context: ActionContext = log_action.execute.call_args[0][0]
        assert context.score is anomaly_score

    def test_skips_unknown_action_id_without_crashing(self, reading_82):
        """action_id referenciado na regra mas ausente no dict não deve travar."""
        rule = Rule(
            name="teste",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["inexistente"],
        )
        engine = make_engine(rules=[rule], actions={})

        # não deve lançar exceção
        engine.evaluate(reading_82)

    def test_disabled_rule_is_skipped(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="desabilitada",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            enabled=False,
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)

        log_action.execute.assert_not_called()

    def test_multiple_rules_evaluated_independently(self, reading_82):
        """Duas regras — só a que bate deve disparar."""
        log_action = make_action()
        webhook_action = make_action()

        rule_high = Rule(
            name="alta_temp",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
        )
        rule_very_high = Rule(
            name="critica",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=90.0),
            action_ids=["webhook"],
        )

        engine = make_engine(
            rules=[rule_high, rule_very_high],
            actions={"log": log_action, "webhook": webhook_action},
        )

        engine.evaluate(reading_82)

        log_action.execute.assert_called_once()       # 82 > 75 — dispara
        webhook_action.execute.assert_not_called()    # 82 < 90 — não dispara


class TestRuleEngineCooldown:

    def test_action_not_called_twice_within_cooldown(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="com_cooldown",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=60.0,
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)   # primeiro disparo — passa
        engine.evaluate(reading_82)   # segundo disparo — bloqueado pelo cooldown

        log_action.execute.assert_called_once()

    def test_action_called_again_after_cooldown(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="cooldown_curto",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=0.1,
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)       # primeiro disparo
        time.sleep(0.15)                  # espera cooldown expirar
        engine.evaluate(reading_82)       # segundo disparo — deve passar

        assert log_action.execute.call_count == 2

    def test_no_cooldown_fires_every_time(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="sem_cooldown",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=0.0,
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)
        engine.evaluate(reading_82)
        engine.evaluate(reading_82)

        assert log_action.execute.call_count == 3


class TestRuleEngineSeverityPropagation:
    """
    A severidade viaja em ActionContext.extras, que já existe em
    core/entities.py:25 — nenhuma assinatura de ActionPort muda por causa dela.
    """

    def _context_of(self, action) -> ActionContext:
        action.execute.assert_called_once()
        return action.execute.call_args.args[0]

    def test_severity_reaches_the_action_context(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="cpu_critica",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            severity=Severity.CRITICAL,
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)

        assert self._context_of(log_action).extras["severity"] == Severity.CRITICAL

    def test_default_severity_reaches_the_action_context(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="alta_temp",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)

        assert self._context_of(log_action).extras["severity"] == Severity.WARNING

    def test_every_action_of_a_rule_receives_the_severity(self, reading_82):
        """Uma regra despacha para N ações — todas precisam ver o mesmo nível."""
        log_action     = make_action()
        webhook_action = make_action()
        rule = Rule(
            name="cpu_critica",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log", "webhook"],
            severity=Severity.CRITICAL,
        )
        engine = make_engine(
            rules=[rule],
            actions={"log": log_action, "webhook": webhook_action},
        )

        engine.evaluate(reading_82)

        assert self._context_of(log_action).extras["severity"] == Severity.CRITICAL
        assert self._context_of(webhook_action).extras["severity"] == Severity.CRITICAL


class TestRuleEngineEventRecording:
    """
    Todo disparo de regra vira um Event no store. Um disparo suprimido por
    cooldown não é disparo, e uma falha do store não pode custar a ação.
    """

    @pytest.fixture
    def store(self) -> MagicMock:
        return MagicMock(spec=EventPort)

    @pytest.fixture
    def critical_rule(self) -> Rule:
        return Rule(
            name="cpu_critica",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            severity=Severity.CRITICAL,
        )

    def _recorded(self, store) -> Event:
        store.append.assert_called_once()
        return store.append.call_args.args[0]

    def test_records_an_event_when_a_rule_fires(self, store, critical_rule, reading_82):
        engine = RuleEngine(rules=[critical_rule], actions={"log": make_action()}, events=store)

        engine.evaluate(reading_82)

        event = self._recorded(store)
        assert event.rule_name     == "cpu_critica"
        assert event.sensor_id     == "cpu_temp"
        assert event.value         == pytest.approx(82.0)
        assert event.unit          == reading_82.unit
        assert event.severity      == "critical"
        assert event.anomaly_score is None

    def test_event_time_is_the_reading_time(self, store, critical_rule, reading_82):
        """
        O evento aconteceu quando o sensor foi lido, não quando o engine
        terminou de avaliar — num tick lento a diferença é visível.
        """
        engine = RuleEngine(rules=[critical_rule], actions={}, events=store)

        engine.evaluate(reading_82)

        assert self._recorded(store).timestamp == reading_82.timestamp

    def test_event_severity_is_a_plain_string(self, store, critical_rule, reading_82):
        """
        str(Severity.CRITICAL) é 'Severity.CRITICAL' no Python 3.10 — o valor
        que chega ao store precisa ser o texto puro, não o membro do enum.
        """
        engine = RuleEngine(rules=[critical_rule], actions={}, events=store)

        engine.evaluate(reading_82)

        assert type(self._recorded(store).severity) is str

    def test_records_the_anomaly_score_when_present(
        self, store, critical_rule, reading_82, anomaly_score
    ):
        engine = RuleEngine(rules=[critical_rule], actions={}, events=store)

        engine.evaluate(reading_82, score=anomaly_score)

        assert self._recorded(store).anomaly_score == pytest.approx(0.91)

    def test_records_nothing_when_no_rule_fires(self, store, critical_rule, reading_72):
        engine = RuleEngine(rules=[critical_rule], actions={}, events=store)

        engine.evaluate(reading_72)

        store.append.assert_not_called()

    def test_cooldown_suppressed_firing_is_not_recorded(self, store, reading_82):
        rule = Rule(
            name="com_cooldown",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=[],
            cooldown_seconds=60.0,
        )
        engine = RuleEngine(rules=[rule], actions={}, events=store)

        engine.evaluate(reading_82)
        engine.evaluate(reading_82)

        store.append.assert_called_once()

    def test_store_failure_does_not_cost_the_action(self, store, critical_rule, reading_82):
        """O alerta é o que importa; o histórico é secundário."""
        store.append.side_effect = RuntimeError("disco cheio")
        log_action = make_action()
        engine = RuleEngine(rules=[critical_rule], actions={"log": log_action}, events=store)

        engine.evaluate(reading_82)

        log_action.execute.assert_called_once()

    def test_store_failure_is_logged(self, store, critical_rule, reading_82, caplog):
        store.append.side_effect = RuntimeError("disco cheio")
        engine = RuleEngine(rules=[critical_rule], actions={}, events=store)

        with caplog.at_level(logging.ERROR, logger="edgesentinel.engine"):
            engine.evaluate(reading_82)

        assert "cpu_critica" in caplog.text
        assert "disco cheio" in caplog.text


class FakeIncidents(IncidentPort):
    """
    Fake em memória com o mesmo invariante do banco: uma regra tem no
    máximo um incidente aberto. Se o engine tentar abrir dois, o teste
    quebra aqui em vez de passar silenciosamente.
    """

    def __init__(self) -> None:
        self.by_id: dict[int, Incident] = {}
        self.opened: list[Incident] = []
        self._next_id = 1

    def open_incident(self, incident: Incident) -> Incident:
        if any(i.rule_name == incident.rule_name and i.is_open for i in self.by_id.values()):
            raise AssertionError(f"dois incidentes abertos para '{incident.rule_name}'")

        stored = dataclasses.replace(incident, incident_id=self._next_id)
        self._next_id += 1
        self.by_id[stored.incident_id] = stored
        self.opened.append(stored)
        return stored

    def acknowledge_incident(self, incident_id: int, at: float) -> None:
        self.by_id[incident_id] = self.by_id[incident_id].acknowledge(at)

    def resolve_incident(self, incident_id: int, at: float) -> None:
        self.by_id[incident_id] = self.by_id[incident_id].resolve(at)

    def open_incidents(self) -> list[Incident]:
        return [i for i in self.by_id.values() if i.is_open]


class TestRuleEngineIncidents:
    """
    Disparos repetidos da mesma regra formam um incidente, que fecha quando
    a leitura recua além da margem de histerese.
    """

    @pytest.fixture
    def incidents(self) -> FakeIncidents:
        return FakeIncidents()

    @pytest.fixture
    def rule(self) -> Rule:
        # resolve em 72.0 (80 menos 10%)
        return Rule(
            name="alta_temp",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=80.0),
            action_ids=["log"],
            severity=Severity.CRITICAL,
        )

    def engine_for(self, rule, incidents, actions=None, events=None) -> RuleEngine:
        return RuleEngine(
            rules=[rule],
            actions=actions or {},
            events=events,
            incidents=incidents,
        )

    def reading(self, value: float, sensor_id: str = "cpu_temp") -> SensorReading:
        return SensorReading(sensor_id, "CPU Temperature", value, "°C")

    def test_the_first_firing_opens_an_incident(self, rule, incidents):
        engine = self.engine_for(rule, incidents)

        engine.evaluate(self.reading(85.0))

        (incident,) = incidents.open_incidents()
        assert incident.rule_name == "alta_temp"
        assert incident.sensor_id == "cpu_temp"
        assert incident.severity == "critical"
        assert incident.state is IncidentState.TRIGGERED

    def test_repeated_firings_stay_in_one_incident(self, rule, incidents):
        engine = self.engine_for(rule, incidents)

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(90.0))
        engine.evaluate(self.reading(95.0))

        assert len(incidents.opened) == 1

    def test_events_point_at_the_incident(self, rule, incidents):
        store = MagicMock(spec=EventPort)
        engine = self.engine_for(rule, incidents, events=store)

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(90.0))

        (incident,) = incidents.open_incidents()
        recorded = [chamada.args[0].incident_id for chamada in store.append.call_args_list]
        assert recorded == [incident.incident_id, incident.incident_id]

    def test_a_reading_past_the_margin_resolves_it(self, rule, incidents):
        engine = self.engine_for(rule, incidents)
        engine.evaluate(self.reading(85.0))

        engine.evaluate(self.reading(70.0))

        assert incidents.open_incidents() == []

    def test_a_reading_inside_the_margin_keeps_it_open(self, rule, incidents):
        engine = self.engine_for(rule, incidents)
        engine.evaluate(self.reading(85.0))

        engine.evaluate(self.reading(79.0))

        assert len(incidents.open_incidents()) == 1

    def test_an_oscillating_series_produces_a_single_incident(self, rule, incidents):
        """O caso que a histerese existe para evitar: flapping na borda."""
        engine = self.engine_for(rule, incidents)

        for value in (85.0, 79.0, 81.0, 78.0, 83.0, 79.5):
            engine.evaluate(self.reading(value))

        assert len(incidents.opened) == 1
        assert len(incidents.open_incidents()) == 1

    def test_resolving_lets_a_later_episode_open_a_new_incident(self, rule, incidents):
        engine = self.engine_for(rule, incidents)

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(60.0))
        engine.evaluate(self.reading(85.0))

        assert len(incidents.opened) == 2

    def test_another_sensor_does_not_resolve_the_incident(self, rule, incidents):
        engine = self.engine_for(rule, incidents)
        engine.evaluate(self.reading(85.0))

        engine.evaluate(self.reading(10.0, sensor_id="memory_usage"))

        assert len(incidents.open_incidents()) == 1

    def test_an_acknowledged_incident_stops_dispatching_actions(self, rule, incidents):
        """Reconhecer é dizer 'já sei' — o alerta para de repetir."""
        log_action = make_action()
        engine = self.engine_for(rule, incidents, actions={"log": log_action})
        engine.evaluate(self.reading(85.0))
        (incident,) = incidents.open_incidents()
        incidents.acknowledge_incident(incident.incident_id, at=time.time())

        engine.evaluate(self.reading(90.0))

        log_action.execute.assert_called_once()   # só o disparo anterior ao ack

    def test_an_acknowledged_incident_still_records_events(self, rule, incidents):
        """O problema continua acontecendo; o histórico tem de mostrar isso."""
        store = MagicMock(spec=EventPort)
        engine = self.engine_for(rule, incidents, events=store)
        engine.evaluate(self.reading(85.0))
        (incident,) = incidents.open_incidents()
        incidents.acknowledge_incident(incident.incident_id, at=time.time())

        engine.evaluate(self.reading(90.0))

        assert store.append.call_count == 2

    def test_an_acknowledged_incident_still_resolves(self, rule, incidents):
        engine = self.engine_for(rule, incidents)
        engine.evaluate(self.reading(85.0))
        (incident,) = incidents.open_incidents()
        incidents.acknowledge_incident(incident.incident_id, at=time.time())

        engine.evaluate(self.reading(60.0))

        assert incidents.open_incidents() == []

    def test_without_an_incident_port_nothing_changes(self, rule):
        """Incidentes são opcionais: sem a porta, o engine age como antes."""
        log_action = make_action()
        engine = RuleEngine(rules=[rule], actions={"log": log_action})

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(60.0))

        log_action.execute.assert_called_once()


class TestRuleEngineCooldownState:
    """
    O cooldown deixa de ser um campo da Rule e passa pelo StatePort. É o que
    permite trocar estado local por Redis em deployment multi-device sem
    mexer no engine.
    """

    @pytest.fixture
    def rule_with_cooldown(self) -> Rule:
        return Rule(
            name="com_cooldown",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=60.0,
        )

    def test_asks_the_state_for_the_rule_cooldown(self, rule_with_cooldown, reading_82):
        state = MagicMock(spec=StatePort)
        state.try_acquire.return_value = True
        engine = RuleEngine(rules=[rule_with_cooldown], actions={}, state=state)

        engine.evaluate(reading_82)

        state.try_acquire.assert_called_once()
        key, ttl = state.try_acquire.call_args.args
        assert "com_cooldown" in key
        assert ttl == pytest.approx(60.0)

    def test_does_not_fire_when_the_state_refuses(self, rule_with_cooldown, reading_82):
        state = MagicMock(spec=StatePort)
        state.try_acquire.return_value = False
        log_action = make_action()
        engine = RuleEngine(rules=[rule_with_cooldown], actions={"log": log_action}, state=state)

        engine.evaluate(reading_82)

        log_action.execute.assert_not_called()

    def test_each_rule_has_its_own_cooldown_key(self, reading_82):
        """Duas regras que casam a mesma leitura não podem consumir um cooldown só."""
        first = Rule(
            name="primeira",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=60.0,
        )
        second = Rule(
            name="segunda",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=80.0),
            action_ids=["log"],
            cooldown_seconds=60.0,
        )
        log_action = make_action()
        engine = make_engine(rules=[first, second], actions={"log": log_action})

        engine.evaluate(reading_82)

        assert log_action.execute.call_count == 2

    def test_rules_no_longer_carry_cooldown_state(self, rule_with_cooldown):
        """O estado saiu da entidade: a Rule volta a ser só a declaração da regra."""
        assert not hasattr(rule_with_cooldown, "_last_triggered")

    def test_the_engine_does_not_read_the_clock_itself(self):
        """
        time.monotonic() não atravessa processos — seu epoch é por processo.
        Se o engine voltar a comparar timestamps, o RedisState não tem como
        fazer o cooldown valer entre dispositivos.
        """
        source = Path(application.engine.__file__).read_text(encoding="utf-8")

        assert "monotonic" not in source

class BrokenIncidents(FakeIncidents):
    """
    Loja de incidentes que falha em uma operação e funciona no resto —
    banco travado, disco cheio, Redis fora do ar. `failing` pode ser
    limpado no meio do teste para simular a volta do serviço.
    """

    def __init__(self, failing: str) -> None:
        super().__init__()
        self.failing: str | None = failing
        self.attempts = 0

    def _maybe_fail(self, operation: str) -> None:
        if operation == self.failing:
            self.attempts += 1
            raise sqlite3.OperationalError("database is locked")

    def open_incident(self, incident: Incident) -> Incident:
        self._maybe_fail("open_incident")
        return super().open_incident(incident)

    def resolve_incident(self, incident_id: int, at: float) -> None:
        self._maybe_fail("resolve_incident")
        super().resolve_incident(incident_id, at)

    def open_incidents(self) -> list[Incident]:
        self._maybe_fail("open_incidents")
        return super().open_incidents()


class TestRuleEngineSurvivesAnIncidentStoreFailure:
    """
    O incidente é contexto do alarme, não o alarme. Se a loja de incidentes
    cair, o disparo continua saindo e o histórico continua sendo escrito:
    o contrário deixaria um disco cheio silenciar a temperatura crítica.
    """

    @pytest.fixture
    def rule(self) -> Rule:
        # resolve em 72.0 (80 menos 10%)
        return Rule(
            name="alta_temp",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=80.0),
            action_ids=["log"],
            severity=Severity.CRITICAL,
        )

    def engine_for(self, rule, incidents, actions=None, events=None) -> RuleEngine:
        return RuleEngine(
            rules=[rule],
            actions=actions or {},
            events=events,
            incidents=incidents,
        )

    def reading(self, value: float) -> SensorReading:
        return SensorReading("cpu_temp", "CPU Temperature", value, "°C")

    def test_a_failing_open_still_alerts_and_records(self, rule, caplog):
        """Sem incidente, o evento vai para o histórico sem incident_id."""
        incidents = BrokenIncidents("open_incident")
        log_action = make_action()
        store = MagicMock(spec=EventPort)
        engine = self.engine_for(rule, incidents, actions={"log": log_action}, events=store)

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(85.0))

        log_action.execute.assert_called_once()
        assert store.append.call_args.args[0].incident_id is None
        assert "alta_temp" in caplog.text

    def test_a_failing_read_of_the_open_incidents_still_alerts(self, rule, caplog):
        incidents = BrokenIncidents("open_incidents")
        log_action = make_action()
        engine = self.engine_for(rule, incidents, actions={"log": log_action})

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(85.0))

        log_action.execute.assert_called_once()
        assert caplog.records, "a falha foi engolida sem registro"

    def test_a_blind_engine_cannot_duplicate_the_incident(self, rule, caplog):
        """
        Sem conseguir ler os abertos, o engine tenta abrir outro a cada
        disparo. Quem recusa é o índice único do banco — aqui, o mesmo
        invariante no fake — e a recusa não pode parar o alerta.
        """
        incidents = BrokenIncidents("open_incidents")
        log_action = make_action()
        engine = self.engine_for(rule, incidents, actions={"log": log_action})

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(85.0))
            engine.evaluate(self.reading(90.0))

        assert len(incidents.opened) == 1
        assert log_action.execute.call_count == 2

    def test_a_failing_resolve_keeps_the_incident_open_for_the_next_reading(self, rule, caplog):
        """
        Falhar ao fechar não pode deixar o incidente meio fechado: ele
        continua aberto e a próxima leitura tenta de novo, porque o engine
        relê o estado a cada avaliação em vez de guardar em memória.
        """
        incidents = BrokenIncidents("resolve_incident")
        engine = self.engine_for(rule, incidents)
        engine.evaluate(self.reading(85.0))

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(70.0))

        assert len(incidents.open_incidents()) == 1
        assert incidents.attempts == 1
        assert "alta_temp" in caplog.text

        incidents.failing = None
        engine.evaluate(self.reading(69.0))

        assert incidents.open_incidents() == []
