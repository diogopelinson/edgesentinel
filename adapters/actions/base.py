from core.ports import ActionPort
from core.entities import ActionContext


class BaseAction(ActionPort):
    """
    The base class for every action.
    Each subclass implements only _run(), with the real logic.
    execute() centralises the error logging, without letting one broken action
    bring the whole pipeline down.
    """

    def __init__(self, action_id: str) -> None:
        self.action_id = action_id

    def execute(self, context: ActionContext) -> None:
        try:
            self._run(context)
        except Exception as e:
            # the action failed, the pipeline carries on
            # in production this goes to the structured logger
            print(f"[{self.action_id}] falha ao executar: {e}")

    def _run(self, context: ActionContext) -> None:
        raise NotImplementedError
