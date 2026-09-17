import logging

from config.mapper import to_rules
from config.schema import ConditionConfig, EdgeSentinelConfig, RuleConfig
from core.rules import Severity


def make_rule(name: str = "alta_temp", **overrides) -> RuleConfig:
    fields = dict(
        name=name,
        condition=ConditionConfig(sensor_id="cpu_temp", operator=">", threshold=75.0),
    )
    fields.update(overrides)
    return RuleConfig(**fields)


def make_config(*rules: RuleConfig, default_actions: dict | None = None) -> EdgeSentinelConfig:
    return EdgeSentinelConfig(
        sensors=[],
        rules=list(rules),
        actions=[],
        default_actions=default_actions or {},
    )


class TestActionResolution:
    """
    Regra com `actions` declarado usa exatamente essa lista. Regra sem
    `actions` herda a lista de default_actions para a sua severidade.
    """

    def test_explicit_actions_are_kept(self):
        rules = to_rules(make_config(make_rule(actions=["log", "webhook"])))

        assert rules[0].action_ids == ["log", "webhook"]

    def test_undeclared_actions_come_from_the_rule_severity(self):
        config = make_config(
            make_rule(severity="critical"),
            default_actions={
                "warning":  ["log"],
                "critical": ["log", "webhook", "buzzer"],
            },
        )

        assert to_rules(config)[0].action_ids == ["log", "webhook", "buzzer"]

    def test_default_severity_uses_the_warning_entry(self):
        config = make_config(
            make_rule(),
            default_actions={"warning": ["log"]},
        )

        assert to_rules(config)[0].action_ids == ["log"]

    def test_explicit_actions_replace_the_defaults_instead_of_merging(self):
        config = make_config(
            make_rule(severity="critical", actions=["log"]),
            default_actions={"critical": ["log", "webhook", "buzzer"]},
        )

        assert to_rules(config)[0].action_ids == ["log"]

    def test_explicit_empty_actions_stay_empty_even_with_defaults(self):
        config = make_config(
            make_rule(severity="critical", actions=[]),
            default_actions={"critical": ["log", "webhook"]},
        )

        assert to_rules(config)[0].action_ids == []

    def test_severity_without_a_default_resolves_to_no_actions(self):
        config = make_config(
            make_rule(severity="info"),
            default_actions={"critical": ["log"]},
        )

        assert to_rules(config)[0].action_ids == []

    def test_no_defaults_and_no_actions_resolves_to_no_actions(self):
        assert to_rules(make_config(make_rule()))[0].action_ids == []

    def test_rules_do_not_share_the_default_list(self):
        """Mexer na lista de uma regra não pode vazar para a outra nem para o config."""
        defaults = {"warning": ["log"]}
        config = make_config(make_rule("a"), make_rule("b"), default_actions=defaults)

        first, second = to_rules(config)
        first.action_ids.append("webhook")

        assert second.action_ids == ["log"]
        assert defaults == {"warning": ["log"]}

    def test_logs_rules_that_resolve_to_no_actions(self, caplog):
        """Pode ser intencional — a regra ainda grava no histórico —, mas precisa ser visível."""
        with caplog.at_level(logging.DEBUG, logger="edgesentinel.config"):
            to_rules(make_config(make_rule(name="silenciosa", severity="info")))

        assert "silenciosa" in caplog.text


class TestExistingMapping:

    def test_severity_becomes_the_enum(self):
        rules = to_rules(make_config(make_rule(severity="critical", actions=["log"])))

        assert rules[0].severity is Severity.CRITICAL

    def test_disabled_rules_are_left_out(self):
        config = make_config(
            make_rule("ligada", actions=["log"]),
            make_rule("desligada", actions=["log"], enabled=False),
        )

        assert [r.name for r in to_rules(config)] == ["ligada"]
