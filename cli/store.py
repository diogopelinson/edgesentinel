"""
From the config path to the history file.

It exists so the query commands fail identically: the same text and the same
exit code when the config will not load or the Event Store is disabled. Two
copies of that decision drift apart the day one of them changes.

Whether the file exists is deliberately not checked here: "no database yet" is a
normal answer for a command that lists and an error for one that changes state,
and each command answers for that difference.
"""
from pathlib import Path

import yaml

from config.loader import load


class StoreIndisponivel(Exception):
    """The history cannot be queried, and the message says why."""


def store_path(config_path: str | Path) -> Path:
    """
    The database path declared in the config.

    Raises StoreIndisponivel in the two cases where no command has anything to
    do: an unreadable config, and a disabled history.
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
