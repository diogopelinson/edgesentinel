from config.schema import EdgeSentinelConfig, RuleConfig, ConditionConfig
from core.rules import Rule, Condition


def to_rules(config: EdgeSentinelConfig) -> list[Rule]:
    """Converte RuleConfig → Rule do core."""
    return [_to_rule(r) for r in config.rules if r.enabled]


def _to_rule(config: RuleConfig) -> Rule:
    return Rule(
        name=config.name,
        condition=_to_condition(config.condition),
        action_ids=config.actions,
        cooldown_seconds=config.cooldown_seconds,
        enabled=config.enabled,
    )


def _to_condition(config: ConditionConfig) -> Condition:
    return Condition(
        sensor_id=config.sensor_id,
        operator=config.operator,
        threshold=config.threshold,
    )