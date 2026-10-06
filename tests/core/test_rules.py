import pytest

from core.rules import Condition, Rule


class TestCondition:

    def test_greater_than_true(self, cpu_reading):
        cond = Condition(sensor_id="cpu_temp", operator=">", threshold=70.0)
        assert cond.evaluate(cpu_reading) is True

    def test_greater_than_false(self, cpu_reading):
        cond = Condition(sensor_id="cpu_temp", operator=">", threshold=80.0)
        assert cond.evaluate(cpu_reading) is False

    def test_less_than(self, cpu_reading):
        cond = Condition(sensor_id="cpu_temp", operator="<", threshold=80.0)
        assert cond.evaluate(cpu_reading) is True

    def test_equal(self, cpu_reading):
        cond = Condition(sensor_id="cpu_temp", operator="==", threshold=72.5)
        assert cond.evaluate(cpu_reading) is True

    def test_wrong_sensor_id_returns_false(self, cpu_reading):
        """A condition for cpu_usage must not evaluate a cpu_temp reading."""
        cond = Condition(sensor_id="cpu_usage", operator=">", threshold=0.0)
        assert cond.evaluate(cpu_reading) is False

    def test_anomaly_operator_true(self, cpu_reading, anomaly_score):
        cond = Condition(sensor_id="cpu_temp", operator="anomaly")
        assert cond.evaluate(cpu_reading, anomaly_score) is True

    def test_anomaly_operator_false(self, cpu_reading, normal_score):
        cond = Condition(sensor_id="cpu_temp", operator="anomaly")
        assert cond.evaluate(cpu_reading, normal_score) is False

    def test_anomaly_operator_without_score_returns_false(self, cpu_reading):
        cond = Condition(sensor_id="cpu_temp", operator="anomaly")
        assert cond.evaluate(cpu_reading, None) is False

    def test_invalid_operator_raises(self, cpu_reading):
        cond = Condition(sensor_id="cpu_temp", operator="??", threshold=70.0)
        with pytest.raises(ValueError, match="Operador desconhecido"):
            cond.evaluate(cpu_reading)


class TestRuleCooldown:

    def test_rule_triggers_on_first_match(self, simple_rule, high_cpu_reading):
        """With no cooldown configured, it must always fire."""
        assert simple_rule.condition.evaluate(high_cpu_reading) is True

    def test_cooldown_is_only_a_declaration(self, high_cpu_reading):
        """
        The Rule declares the cooldown; the engine is what applies it, through
        the StatePort (see tests/application/test_engine.py and tests/adapters/
        test_state_contract.py). Here only the declared value matters.
        """
        rule = Rule(
            name="teste_cooldown",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=60.0,
        )

        assert rule.cooldown_seconds == 60.0
        assert rule.condition.evaluate(high_cpu_reading) is True
