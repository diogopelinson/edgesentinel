import time
import pytest

from unittest.mock import MagicMock, call
from core.rules import Rule, Condition
from core.entities import SensorReading, AnomalyScore, ActionContext
from core.ports import ActionPort
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