import logging

from config.schema import EdgeSentinelConfig, RuleConfig, ConditionConfig
from core.rules import Rule, Condition, Severity

logger = logging.getLogger("edgesentinel.config")


def to_rules(config: EdgeSentinelConfig) -> list[Rule]:
    """Converte RuleConfig → Rule do core."""
    return [
        _to_rule(r, config.default_actions)
        for r in config.rules
        if r.enabled
    ]


def _to_rule(config: RuleConfig, default_actions: dict[str, list[str]]) -> Rule:
    severity = Severity.from_name(config.severity)
    return Rule(
        name=config.name,
        condition=_to_condition(config.condition),
        action_ids=_resolve_actions(config, severity, default_actions),
        severity=severity,
        cooldown_seconds=config.cooldown_seconds,
        enabled=config.enabled,
    )


def _resolve_actions(
    config: RuleConfig,
    severity: Severity,
    default_actions: dict[str, list[str]],
) -> list[str]:
    """
    `actions` declarado substitui o padrão — nunca mescla. Sem `actions`,
    vale default_actions da severidade da regra.

    Sempre devolve uma cópia: regras que herdam o mesmo padrão não podem
    compartilhar a mesma lista.
    """
    if config.actions is not None:
        action_ids = list(config.actions)
    else:
        action_ids = list(default_actions.get(severity.value, []))

    if not action_ids:
        logger.debug(
            f"Regra '{config.name}' [{severity.value}] sem ações — "
            f"só registra no histórico."
        )

    return action_ids


def _to_condition(config: ConditionConfig) -> Condition:
    return Condition(
        sensor_id=config.sensor_id,
        operator=config.operator,
        threshold=config.threshold,
        resolve_threshold=config.resolve_threshold,
    )
