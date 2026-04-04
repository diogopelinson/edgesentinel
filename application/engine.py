import time
import logging

from core.rules import Rule
from core.entities import SensorReading, AnomalyScore, ActionContext
from core.ports import ActionPort

logger = logging.getLogger("edgesentinel.engine")


class RuleEngine:
    """
    Avalia regras contra uma leitura e executa as ações correspondentes.
    Respeita o cooldown de cada regra para evitar spam de alertas.
    """

    def __init__(
        self,
        rules: list[Rule],
        actions: dict[str, ActionPort],
    ) -> None:
        self._rules = rules
        self._actions = actions

    def evaluate(
        self,
        reading: SensorReading,
        score: AnomalyScore | None = None,
    ) -> None:
        """
        Recebe uma leitura (e opcionalmente um score de anomalia)
        e dispara as ações de cada regra cuja condição for verdadeira.
        """
        for rule in self._rules:
            if not rule.enabled:
                continue

            if not rule.condition.evaluate(reading, score):
                continue

            if not self._cooldown_ok(rule):
                logger.debug(f"Regra '{rule.name}' em cooldown, ignorando.")
                continue

            self._trigger(rule, reading, score)

    # --- métodos privados ---

    def _cooldown_ok(self, rule: Rule) -> bool:
        """Retorna True se o cooldown já passou desde o último disparo."""
        if rule.cooldown_seconds <= 0:
            return True
        elapsed = time.monotonic() - rule._last_triggered
        return elapsed >= rule.cooldown_seconds

    def _trigger(
        self,
        rule: Rule,
        reading: SensorReading,
        score: AnomalyScore | None,
    ) -> None:
        """Executa todas as ações da regra e atualiza o timestamp de disparo."""
        rule._last_triggered = time.monotonic()

        context = ActionContext(
            rule_name=rule.name,
            reading=reading,
            score=score,
        )

        logger.info(f"Regra '{rule.name}' disparada para sensor '{reading.sensor_id}'.")

        for action_id in rule.action_ids:
            action = self._actions.get(action_id)
            if action is None:
                logger.warning(f"Action '{action_id}' não encontrada, ignorando.")
                continue
            action.execute(context)