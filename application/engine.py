import logging

from core.rules import Rule
from core.entities import SensorReading, AnomalyScore, ActionContext, Event
from core.incidents import Incident, IncidentState
from core.ports import ActionPort, EventPort, IncidentPort, StatePort

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
        incidents: IncidentPort | None = None,
    ) -> None:
        self._rules = rules
        self._actions = actions
        self._events = events
        self._state = state if state is not None else self._default_state()
        self._incidents = incidents

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
        Recebe uma leitura (e opcionalmente um score de anomalia) e dispara
        as ações de cada regra cuja condição for verdadeira.

        Regras com incidente aberto que deixaram de casar também são
        avaliadas: é onde o incidente fecha.
        """
        open_incidents = self._open_incidents_by_rule()

        for rule in self._rules:
            if not rule.enabled:
                continue

            incident = open_incidents.get(rule.name)

            if rule.condition.evaluate(reading, score):
                if not self._cooldown_ok(rule):
                    logger.debug(f"Regra '{rule.name}' em cooldown, ignorando.")
                    continue
                self._trigger(rule, reading, score, incident)

            elif incident is not None and rule.condition.resolves(reading, score):
                self._resolve(rule, incident, reading)

    # --- métodos privados ---

    def _open_incidents_by_rule(self) -> dict[str, Incident]:
        """
        Lê os incidentes abertos a cada avaliação, em vez de guardar em
        memória. É assim que o agente vê um reconhecimento feito por outro
        processo (a CLI), e é o que faz o ciclo sobreviver a um restart sem
        etapa de carga.
        """
        if self._incidents is None:
            return {}

        try:
            return {i.rule_name: i for i in self._incidents.open_incidents()}
        except Exception as e:
            logger.error(f"Falha ao ler incidentes abertos: {e}")
            return {}

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
        incident: Incident | None,
    ) -> None:
        """
        Registra o disparo e executa as ações. Sem incidente aberto, abre um;
        com um já aberto, o disparo se junta a ele.
        """
        if incident is None:
            incident = self._open_incident(rule, reading)

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

        self._record(rule, reading, score, incident)

        if incident is not None and incident.state is IncidentState.ACKNOWLEDGED:
            # reconhecer é dizer "já sei": o histórico continua, o alerta não
            logger.debug(
                f"Incidente #{incident.incident_id} de '{rule.name}' reconhecido "
                f"— ações não repetem."
            )
            return

        for action_id in rule.action_ids:
            action = self._actions.get(action_id)
            if action is None:
                logger.warning(f"Action '{action_id}' não encontrada, ignorando.")
                continue
            action.execute(context)

    def _open_incident(self, rule: Rule, reading: SensorReading) -> Incident | None:
        """
        Abre o incidente do episódio. Falha é logada e engolida, como no
        histórico: sem incidente o alerta ainda tem de sair.
        """
        if self._incidents is None:
            return None

        try:
            incident = self._incidents.open_incident(Incident(
                rule_name=rule.name,
                sensor_id=reading.sensor_id,
                severity=rule.severity.value,
                opened_at=reading.timestamp,
            ))
            logger.info(
                f"Incidente #{incident.incident_id} aberto para '{rule.name}' "
                f"[{rule.severity.value}]."
            )
            return incident
        except Exception as e:
            logger.error(f"Falha ao abrir incidente de '{rule.name}': {e}")
            return None

    def _resolve(self, rule: Rule, incident: Incident, reading: SensorReading) -> None:
        """Fecha o incidente quando a leitura recua além da margem."""
        # As duas invariantes vêm de _open_incidents_by_rule: sem store não há
        # incidente aberto para chegar aqui, e todo incidente que veio do store
        # tem id. Declaradas para o verificador de tipos e para quebrar alto se
        # alguém mudar aquele caminho — passar None ao store falharia calado.
        assert self._incidents is not None
        assert incident.incident_id is not None

        try:
            self._incidents.resolve_incident(incident.incident_id, at=reading.timestamp)
            logger.info(
                f"Incidente #{incident.incident_id} de '{rule.name}' resolvido "
                f"em {reading.value}{reading.unit}."
            )
        except Exception as e:
            logger.error(f"Falha ao resolver incidente de '{rule.name}': {e}")

    def _record(
        self,
        rule: Rule,
        reading: SensorReading,
        score: AnomalyScore | None,
        incident: Incident | None = None,
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
                incident_id=incident.incident_id if incident is not None else None,
            ))
        except Exception as e:
            logger.error(f"Falha ao registrar evento da regra '{rule.name}': {e}")
