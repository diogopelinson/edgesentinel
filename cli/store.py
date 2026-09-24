"""
Do caminho do config ao arquivo do histórico.

Existe para os comandos de consulta falharem igual: o mesmo texto e o mesmo
código de saída quando o config não carrega ou o Event Store está desligado.
Duas cópias dessa decisão divergem no dia em que uma delas muda.

A existência do arquivo não é checada aqui de propósito: 'não há banco ainda'
é resposta normal para quem lista e é erro para quem muda estado, e cada
comando responde por essa diferença.
"""
from pathlib import Path

import yaml

from config.loader import load


class StoreIndisponivel(Exception):
    """O histórico não pode ser consultado, e a mensagem diz por quê."""


def store_path(config_path: str | Path) -> Path:
    """
    Caminho do banco declarado no config.

    Levanta StoreIndisponivel nos dois casos em que nenhum comando tem o que
    fazer: config ilegível e histórico desabilitado.
    """
    try:
        config = load(config_path)
    except (OSError, ValueError, yaml.YAMLError) as e:
        raise StoreIndisponivel(f"Erro: {e}") from e

    if not config.event_store.enabled:
        raise StoreIndisponivel(
            f"Event Store desabilitado em {config_path} — "
            f"não há histórico para consultar."
        )

    return Path(config.event_store.path)
