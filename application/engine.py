import logging

from core.rules import Rule
from core.entities import SensorReading, AnomalyScore, ActionContext, Event
from core.ports import ActionPort, EventPort, StatePort

logger = logging.getLogger("edgesentinel.engine")

_COOLDOWN_PREFIX = "cooldown:"


class RuleEngine:
    """
    Avalia regras contra uma leitura e executa as ações correspondentes.
    Respeita o cooldown de cada regra para evitar spam de alertas.
    Com um EventPort, cada disparo também vira um registro no histórico.

    O cooldown passa pelo StatePort, nunca pelo relógio: é o que permite,
    em deployment multi-device, trocar o estado local pelo Redis sem mexer
    aqui.
    """

    def __init__(
        self,
        rules: list[Rule],
        actions: dict[str, ActionPort],
        events: EventPort | None = None,
        state: StatePort | None = None,
    ) -> None:
        self._rules = rules
        self._actions = actions
        self._events = events
        self._state = state if state is not None else self._default_state()

    @staticmethod
    def _default_state() -> StatePort:
        """
        Import local: o default é um adapter, e o módulo do engine importa
        só o core no topo.
        """
        from adapters.state.memory import InMemoryState
        return InMemoryState()

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
        """
        Toma o cooldown da regra. Tomar e verificar são a mesma operação no
        StatePort — separá-los deixava duas threads do executor disparar a
        mesma regra.
        """
        return self._state.try_acquire(
            f"{_COOLDOWN_PREFIX}{rule.name}",
            rule.cooldown_seconds,
        )

    def _trigger(
        self,
        rule: Rule,
        reading: SensorReading,
        score: AnomalyScore | None,
    ) -> None:
        """Executa todas as ações da regra e registra o evento."""
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