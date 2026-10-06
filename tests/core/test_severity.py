import pytest

from core.rules import Rule, Condition, Severity


class TestSeverity:

    def test_has_three_levels(self):
        assert [s.value for s in Severity] == ["info", "warning", "critical"]

    def test_from_name_is_case_insensitive(self):
        """The YAML is written by humans — 'CRITICAL' and 'Critical' are the same level."""
        assert Severity.from_name("critical") is Severity.CRITICAL
        assert Severity.from_name("CRITICAL") is Severity.CRITICAL
        assert Severity.from_name("Warning") is Severity.WARNING

    def test_from_name_rejects_unknown_level(self):
        with pytest.raises(ValueError) as exc:
            Severity.from_name("catastrophic")

        message = str(exc.value)
        assert "catastrophic" in message
        assert "info" in message
        assert "warning" in message
        assert "critical" in message

    def test_compares_equal_to_its_string_value(self):
        """
        Severity is a str Enum so it crosses ActionContext.extras and, later,
        serialization to the Event Store without a conversion at every boundary.
        """
        assert Severity.CRITICAL == "critical"


class TestRuleSeverity:

    def test_defaults_to_warning(self):
        """A rule with no declared severity keeps behaving as it does today."""
        rule = Rule(
            name="alta_temp",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
        )

        assert rule.severity is Severity.WARNING

    def test_accepts_explicit_severity(self):
        rule = Rule(
            name="cpu_critica",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=90.0),
            action_ids=["log"],
            severity=Severity.CRITICAL,
        )

        assert rule.severity is Severity.CRITICAL
