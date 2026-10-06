import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from adapters.store.sqlite import SQLiteEventStore
from cli.render import COLORS, RESET
from cli.store import StoreIndisponivel, store_path
from core.entities import Event

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION     = re.compile(r"^(\d+)([smhd])$")

_HEADERS     = ("QUANDO", "SEVERIDADE", "REGRA", "SENSOR", "VALOR", "SCORE")
_RIGHT_ALIGN = {4, 5}      # the numeric columns


def parse_duration(text: str) -> float:
    """'30m' → 1800.0. Takes s, m, h and d, case-insensitively."""
    match = _DURATION.match(text.strip().lower())
    if not match or int(match.group(1)) == 0:
        raise ValueError(
            f"Duração inválida: '{text}'. Use um inteiro positivo seguido "
            f"de s, m, h ou d — por exemplo 30m, 24h ou 7d."
        )
    return float(int(match.group(1)) * _UNIT_SECONDS[match.group(2)])


def run_events(
    config_path: str | Path,
    *,
    severity: str | None = None,
    sensor: str | None = None,
    rule: str | None = None,
    window_seconds: float | None = None,
    limit: int = 20,
    as_json: bool = False,
    now: float | None = None,
) -> int:
    """
    Lists the history of rules that fired. Returns the exit code.

    stdout carries data only — a table or JSON Lines. Status messages go to
    stderr, so that `--json | jq` never receives loose text.
    """
    try:
        path = store_path(config_path)
    except StoreIndisponivel as e:
        _status(str(e))
        return 1

    if not path.exists():
        # checked before opening: sqlite3.connect would create an empty file
        _status(f"Nenhum evento registrado ainda — {path} não existe.")
        return 0

    since = None
    if window_seconds is not None:
        since = (time.time() if now is None else now) - window_seconds

    # no start(): that applies the retention and spins up the writer thread,
    # and a query must neither delete anything nor leave a thread behind
    store = SQLiteEventStore(path=path)
    try:
        events = store.query(
            severity=severity,
            sensor_id=sensor,
            rule_name=rule,
            since=since,
            limit=limit,
        )
    except sqlite3.Error as e:
        _status(f"Erro: não foi possível ler {path}: {e}")
        return 1

    if as_json:
        for event in events:
            print(json.dumps(_to_record(event), ensure_ascii=False))
        if not events:
            _status("Nenhum evento encontrado com esses filtros.")
        return 0

    if not events:
        _status("Nenhum evento encontrado com esses filtros.")
        return 0

    print(format_table(events, color=sys.stdout.isatty()))
    print()
    print(_footer(len(events), limit))
    return 0


def format_table(events: list[Event], color: bool = False) -> str:
    # the unit is padded to the widest one: with the column right-aligned it is
    # the numbers that line up, not the units
    unit_width = max((len(e.unit) for e in events), default=0)
    rows = [
        (
            datetime.fromtimestamp(e.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
            e.severity.upper(),
            e.rule_name,
            e.sensor_id,
            f"{e.value:.2f} {e.unit.ljust(unit_width)}",
            f"{e.anomaly_score:.2f}" if e.anomaly_score is not None else "-",
        )
        for e in events
    ]
    widths = [
        max([len(header)] + [len(row[i]) for row in rows])
        for i, header in enumerate(_HEADERS)
    ]

    def render(cells: tuple[str, ...], severity: str | None = None) -> str:
        padded = [
            cell.rjust(width) if i in _RIGHT_ALIGN else cell.ljust(width)
            for i, (cell, width) in enumerate(zip(cells, widths, strict=True))
        ]
        # color applied after the padding: an ANSI escape occupies no column
        if color and severity in COLORS:
            padded[1] = f"{COLORS[severity]}{padded[1]}{RESET}"
        return "  ".join(padded).rstrip()

    lines = [render(_HEADERS)]
    lines += [render(row, e.severity) for row, e in zip(rows, events, strict=True)]
    return "\n".join(lines)


def _footer(count: int, limit: int) -> str:
    text = f"{count} evento(s)"
    if count >= limit:
        text += f" — mostrando os {limit} mais recentes; use --limit para ver mais"
    return text


def _to_record(event: Event) -> dict:
    local = datetime.fromtimestamp(event.timestamp).astimezone()
    return {
        "event_id":      event.event_id,
        "time":          local.isoformat(timespec="seconds"),
        "timestamp":     event.timestamp,
        "severity":      event.severity,
        "rule_name":     event.rule_name,
        "sensor_id":     event.sensor_id,
        "value":         event.value,
        "unit":          event.unit,
        "anomaly_score": event.anomaly_score,
        "incident_id":   event.incident_id,
    }


def _status(message: str) -> None:
    print(message, file=sys.stderr)
