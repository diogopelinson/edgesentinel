import logging
from adapters.actions.base import BaseAction
from core.entities import ActionContext
from core.rules import Severity

logger = logging.getLogger("edgesentinel.action.log")

# O core não conhece o módulo logging — o mapeamento vive no adapter.
_SEVERITY_LEVELS: dict[Severity, int] = {
    Severity.INFO:     logging.INFO,
    Severity.WARNING:  logging.WARNING,
    Severity.CRITICAL: logging.CRITICAL,
}


class LogAction(BaseAction):
    """
    Escreve um log estruturado quando uma regra dispara.
    Usa o módulo logging padrão do Python — compatível com
    qualquer handler: console, arquivo, syslog, etc.
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
        A severidade da regra descreve o evento específico e vence o nível do
        construtor, que é apenas o default da ação para todas as regras.
        """
        severity = context.extras.get("severity")
        return _SEVERITY_LEVELS.get(severity, self.level)