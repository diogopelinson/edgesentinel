from core.ports import ActionPort
from core.entities import ActionContext


class BaseAction(ActionPort):
    """
    Classe base para todas as ações.
    Cada filho implementa apenas _run() com a lógica real.
    O execute() centraliza logging de erro sem deixar uma ação
    quebrada derrubar o pipeline inteiro.
    """

    def __init__(self, action_id: str) -> None:
        self.action_id = action_id

    def execute(self, context: ActionContext) -> None:
        try:
            self._run(context)
        except Exception as e:
            # ação falhou mas o pipeline continua
            # em produção isso vai pro logger estruturado
            print(f"[{self.action_id}] falha ao executar: {e}")

    def _run(self, context: ActionContext) -> None:
        raise NotImplementedError