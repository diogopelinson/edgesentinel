import logging

from core.rules import Rule
from core.entities import SensorReading, AnomalyScore, ActionContext, Event
from core.incidents import Incident, IncidentState
from core.ports import (
    ActionPort,
    EventPort,
    IncidentMetricsPort,
    IncidentPort,
    StatePort,
)

logger = logging.getLogger("edgesentinel.engine")

_COOLDOWN_PREFIX = "cooldown:"


class RuleEngine:
    """
    Evaluates rules against a reading and runs the matching actions.
    Respects each rule's cooldown so alerts do not spam.
    With an EventPort, every firing also becomes a row in the history.

    The cooldown goes through the StatePort, never through the clock: that is
    what lets a multi-device deployment swap local state for Redis without
    touching anything here.
    """

    def __init__(
        self,
        rules: list[Rule],
        actions: dict[str, ActionPort],
        events: EventPort | None = None,
        state: StatePort | None = None,
        incidents: IncidentPort | None = None,
        metrics: IncidentMetricsPort | None = None,
    ) -> None:
        self._rules = rules
        self._actions = actions
        self._events = events
        self._state = state if state is not None else self._default_state()
        self._incidents = incidents
        self._metrics = metrics

    @staticmethod
    def _default_state() -> StatePort:
        """
        Local import: the default is an adapter, and the engine module imports
        only core at the top.
        """
        from adapters.state.memory import InMemoryState
        return InMemoryState()

    def evaluate(
        self,
        reading: SensorReading,
        score: AnomalyScore | None = None,
    ) -> None:
        """
        Takes a reading (and optionally an anomaly score) and runs the actions
        of every rule whose condition holds.

        Rules with an open incident that stopped matching are evaluated too:
        that is where the incident closes.
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

    # --- private methods ---

    def _open_incidents_by_rule(self) -> dict[str, Incident]:
        """
        Reads the open incidents on every evaluation instead of keeping them
        in memory. That is how the agent sees an acknowledgement made by
        another process (the CLI), and it is what makes the lifecycle survive a
        restart with no loading step.
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
        Takes the rule's cooldown. Taking and checking are one operation in
        the StatePort — splitting them let two executor threads fire the same
        rule.
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
        Records the firing and runs the actions. With no incident open it opens
        one; with one already open the firing joins it.
        """
        if incident is None:
            incident = self._open_incident(rule, reading)

        # built once per rule, not per action — every action of one firing has
        # to observe exactly the same context
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
            # acknowledging says "I know": the history goes on, the alert does not
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
        Opens the episode's incident. A failure is logged and swallowed, like
        in the history: with no incident, the alert still has to go out.
        """
        if self._incidents is None:
            return None

        # the try covers the store and only the store. With the counting
        # inside, a metric that raised would land in this except: the engine
        # would give up on an incident the database had already opened, the
        # event would be written with no incident_id, and the log would say the
        # open had failed
        try:
            incident = self._incidents.open_incident(Incident(
                rule_name=rule.name,
                sensor_id=reading.sensor_id,
                severity=rule.severity.value,
                opened_at=reading.timestamp,
            ))
        except Exception as e:
            logger.error(f"Falha ao abrir incidente de '{rule.name}': {e}")
            return None

        logger.info(
            f"Incidente #{incident.incident_id} aberto para '{rule.name}' "
            f"[{rule.severity.value}]."
        )
        self._count_opened(incident)
        return incident

    def _resolve(self, rule: Rule, incident: Incident, reading: SensorReading) -> None:
        """Closes the incident once the reading comes back past the margin."""
        # Both invariants come from _open_incidents_by_rule: with no store
        # there is no open incident to get here, and every incident that came
        # from the store has an id. Stated for the type checker and to fail
        # loudly if someone changes that path — passing None to the store would
        # fail silently.
        assert self._incidents is not None
        assert incident.incident_id is not None

        try:
            self._incidents.resolve_incident(incident.incident_id, at=reading.timestamp)
        except Exception as e:
            logger.error(f"Falha ao resolver incidente de '{rule.name}': {e}")
            return

        logger.info(
            f"Incidente #{incident.incident_id} de '{rule.name}' resolvido "
            f"em {reading.value}{reading.unit}."
        )
        # the duration is the distance between the two readings, not how long
        # the evaluation took — it is how long the problem lasted
        self._count_resolved(incident, reading.timestamp - incident.opened_at)

    def _count_opened(self, incident: Incident) -> None:
        """
        Counts the episode opening. Once per incident: a firing that joins an
        already open incident does not come through here, or the opening rate
        would track the polling interval instead of the problem.
        """
        if self._metrics is None:
            return

        try:
            self._metrics.record_incident_opened(incident)
        except Exception as e:
            logger.error(f"Falha ao contabilizar a abertura do incidente: {e}")

    def _count_resolved(self, incident: Incident, duration_seconds: float) -> None:
        """
        Counts the close. Only called after the store accepted it: counting a
        resolve that failed would make opened-minus-resolved drift away from
        what is on disk.

        A failure here is logged and swallowed, like in the actions and the
        history — the metric is an observation of the alarm, not the alarm.
        """
        if self._metrics is None:
            return

        try:
            self._metrics.record_incident_resolved(incident, duration_seconds)
        except Exception as e:
            logger.error(f"Falha ao contabilizar o fechamento do incidente: {e}")

    def _record(
        self,
        rule: Rule,
        reading: SensorReading,
        score: AnomalyScore | None,
        incident: Incident | None = None,
    ) -> None:
        """
        Records the firing in the history. A failure here is logged and
        swallowed: the alert is what matters, and the actions still have to run.
        """
        if self._events is None:
            return

        try:
            self._events.append(Event(
                rule_name=rule.name,
                sensor_id=reading.sensor_id,
                value=reading.value,
                unit=reading.unit,
                # .value, never str(): on 3.10 str(Severity.X) is 'Severity.X'
                severity=rule.severity.value,
                # the event happened at the reading, not at the end of the evaluation
                timestamp=reading.timestamp,
                anomaly_score=score.score if score is not None else None,
                incident_id=incident.incident_id if incident is not None else None,
            ))
        except Exception as e:
            logger.error(f"Falha ao registrar evento da regra '{rule.name}': {e}")
