import logging
from adapters.actions.base import BaseAction
from core.entities import ActionContext
from core.rules import Severity

logger = logging.getLogger("edgesentinel.action.log")

# core knows nothing about the logging module — the mapping lives in the adapter.
_SEVERITY_LEVELS: dict[Severity, int] = {
    Severity.INFO:     logging.INFO,
    Severity.WARNING:  logging.WARNING,
    Severity.CRITICAL: logging.CRITICAL,
}


class LogAction(BaseAction):
    """
    Writes a structured log line when a rule fires.
    Uses Python's standard logging module, so it works with any handler:
    console, file, syslog and so on.
    """

    def __init__(self, action_id: str = "log", level: str = "WARNING") -> None:
        super().__init__(action_id)
        self.level = getattr(logging, level.upper(), logging.WARNING)

    def _run(self, context: ActionContext) -> None:
        reading = context.reading
        score = context.score

        message = (
            f"Regra '{context.rule_name}' disparada | "
            f"sensor={reading.sensor_id} "
            f"value={reading.value}{reading.unit}"
        )

        if score is not None:
            message += f" | anomaly_score={score.score} threshold={score.threshold}"

        logger.log(self._level_for(context), message)

    def _level_for(self, context: ActionContext) -> int:
        """
        The rule's severity describes this particular event and beats the level
        from the constructor, which is only the action's default across rules.
        """
        severity = context.extras.get("severity")
        return _SEVERITY_LEVELS.get(severity, self.level)
