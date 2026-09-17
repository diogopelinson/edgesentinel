import time
import logging

from core.rules import Rule
from core.entities import SensorReading, AnomalyScore, ActionContext, Event
from core.ports import ActionPort, EventPort

logger = logging.getLogger("edgesentinel.engine")


class RuleEngine:
    """
    Avalia regras contra uma leitura e executa as ações correspondentes.
    Respeita o cooldown de cada regra para evitar spam de alertas.
    Com um EventPort, cada disparo também vira um registro no histórico.
    """

    def __init__(
        self,
        rules: list[Rule],
        actions: dict[str, ActionPort],
        events: EventPort | None = None,
    ) -> None:
        self._rules = rules
        self._actions = actions
        self._events = events

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

        # construído uma vez por regra, não por ação — todas as ações de um
        # mesmo disparo precisam observar exatamente o mesmo contexto
        context = ActionContext(
            rule_name=rule.name,
            reading=reading,
            score=score,
            extras={"severity": rule.severity},
        )

        logger.info(
            f"Regra '{rule.name}' [{rule.severity.value}] disparada "
            f"para sensor '{reading.sensor_id}'."
        )

        self._record(rule, reading, score)

        for action_id in rule.action_ids:
            action = self._actions.get(action_id)
            if action is None:
                logger.warning(f"Action '{action_id}' não encontrada, ignorando.")
                continue
            action.execute(context)

    def _record(
        self,
        rule: Rule,
        reading: SensorReading,
        score: AnomalyScore | None,
    ) -> None:
        """
        Registra o disparo no histórico. Uma falha aqui é logada e engolida:
        o alerta é o que importa, e as ações ainda precisam rodar.
        """
        if self._events is None:
            return

        try:
            self._events.append(Event(
                rule_name=rule.name,
                sensor_id=reading.sensor_id,
                value=reading.value,
                unit=reading.unit,
                # .value, nunca str(): no 3.10 str(Severity.X) é 'Severity.X'
                severity=rule.severity.value,
                # o evento aconteceu na leitura, não no fim da avaliação
                timestamp=reading.timestamp,
                anomaly_score=score.score if score is not None else None,
            ))
        except Exception as e:
            logger.error(f"Falha ao registrar evento da regra '{rule.name}': {e}")