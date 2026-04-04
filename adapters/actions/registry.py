from adapters.actions.base import BaseAction
from adapters.actions.log import LogAction
from adapters.actions.webhook import WebhookAction
from adapters.actions.gpio import GPIOWriteAction
from config.schema import ActionConfig


def build_action(config: ActionConfig) -> BaseAction:
    """
    Recebe um ActionConfig vindo do YAML e retorna a instância correta.

    Exemplo de config:
        id: webhook
        type: webhook
        url: https://hooks.exemplo.com/alerta
    """
    match config.type:
        case "log":
            return LogAction(action_id=config.id)

        case "webhook":
            if not config.url:
                raise ValueError(
                    f"Action '{config.id}' do tipo webhook precisa de 'url' no config."
                )
            return WebhookAction(action_id=config.id, url=config.url)

        case "gpio_write":
            return GPIOWriteAction(action_id=config.id)

        case _:
            supported = "log, webhook, gpio_write"
            raise ValueError(
                f"Tipo de action desconhecido: '{config.type}'. "
                f"Suportados: {supported}"
            )


def build_actions(configs: list[ActionConfig]) -> dict[str, BaseAction]:
    """
    Constrói todas as ações e devolve um dict indexado pelo id.
    O RuleEngine vai usar esse dict para resolver action_ids das regras.

    Exemplo:
        {"log": LogAction, "webhook": WebhookAction}
    """
    return {config.id: build_action(config) for config in configs}