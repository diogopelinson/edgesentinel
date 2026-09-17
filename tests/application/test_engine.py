import logging
import time
import pytest

from unittest.mock import MagicMock, call
from core.rules import Rule, Condition, Severity
from core.entities import SensorReading, AnomalyScore, ActionContext
from core.ports import ActionPort, EventPort
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

    def _recorded(self, store) -> "Event":
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