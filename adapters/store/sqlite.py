import logging
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from core.entities import Event
from core.ports import EventPort

logger = logging.getLogger("edgesentinel.store")

_SCHEMA_VERSION  = 1
_SECONDS_PER_DAY = 86_400

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     REAL    NOT NULL,
    rule_name     TEXT    NOT NULL,
    sensor_id     TEXT    NOT NULL,
    value         REAL    NOT NULL,
    unit          TEXT    NOT NULL,
    severity      TEXT    NOT NULL,
    anomaly_score REAL
);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp);
CREATE INDEX IF NOT EXISTS idx_events_severity  ON events (severity, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_sensor    ON events (sensor_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_rule      ON events (rule_name, timestamp);
"""

_COLUMNS = "event_id, timestamp, rule_name, sensor_id, value, unit, severity, anomaly_score"

_INSERT = (
    "INSERT INTO events (timestamp, rule_name, sensor_id, value, unit, severity, anomaly_score) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)

# sinaliza para a thread de escrita que não virá mais nada
_STOP = object()


class SQLiteEventStore(EventPort):
    """
    Histórico de regras disparadas num arquivo SQLite local.

    append() só enfileira; uma thread dedicada grava em lote. O pipeline roda
    em run_in_executor, num pool limitado — num cartão SD, um fsync pode
    travar por centenas de milissegundos, e esse atraso não pode segurar o
    worker que está lendo sensores.

    Com a fila cheia o evento é descartado com aviso: perder um registro do
    histórico é preferível a atrasar o próximo alerta.
    """

    def __init__(
        self,
        path: str | Path,
        retention_days: float = 30.0,
        queue_size: int = 1000,
        batch_size: int = 50,
    ) -> None:
        self._path           = Path(path)
        self._retention_days = retention_days
        self._batch_size     = batch_size
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._writer: threading.Thread | None = None

    # --- ciclo de vida ---

    def start(self) -> None:
        if self._writer is not None:
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            # WAL deixa query() ler enquanto a thread de escrita grava
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

        cutoff  = time.time() - self._retention_days * _SECONDS_PER_DAY
        removed = self.prune(before=cutoff)
        if removed:
            logger.info(
                f"{removed} evento(s) além da retenção de "
                f"{self._retention_days:g} dia(s) removido(s)."
            )

        self._writer = threading.Thread(
            target=self._drain,
            name="edgesentinel-event-writer",
            daemon=True,
        )
        self._writer.start()
        logger.info(f"Event Store aberto em {self._path}")

    def close(self, timeout: float = 5.0) -> None:
        if self._writer is None:
            return

        try:
            self._queue.put(_STOP, timeout=timeout)
        except queue.Full:
            logger.warning("Fila de eventos não esvaziou a tempo — encerrando sem gravar tudo.")

        self._writer.join(timeout)
        if self._writer.is_alive():
            logger.warning("Thread de escrita não encerrou dentro do prazo.")
        self._writer = None

    # --- escrita ---

    def append(self, event: Event) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning(
                f"Fila de eventos cheia — evento da regra "
                f"'{event.rule_name}' descartado."
            )

    def flush(self, timeout: float = 5.0) -> bool:
        """
        Espera a fila esvaziar. Devolve False se o prazo acabar antes.
        Não faz parte do EventPort: existe para testes determinísticos.
        """
        if self._writer is None:
            return self._queue.unfinished_tasks == 0

        deadline = time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
        return True

    def _drain(self) -> None:
        """Loop da thread de escrita. A conexão pertence só a esta thread."""
        conn = sqlite3.connect(self._path)
        try:
            while True:
                batch = [self._queue.get()]
                while len(batch) < self._batch_size:
                    try:
                        batch.append(self._queue.get_nowait())
                    except queue.Empty:
                        break

                events = [item for item in batch if item is not _STOP]
                try:
                    if events:
                        self._write(conn, events)
                except Exception as e:
                    conn.rollback()
                    logger.error(f"Falha ao gravar {len(events)} evento(s): {e}")
                finally:
                    for _ in batch:
                        self._queue.task_done()

                if len(events) != len(batch):
                    return
        finally:
            conn.close()

    @staticmethod
    def _write(conn: sqlite3.Connection, events: list[Event]) -> None:
        conn.executemany(_INSERT, [
            (e.timestamp, e.rule_name, e.sensor_id, e.value,
             e.unit, e.severity, e.anomaly_score)
            for e in events
        ])
        conn.commit()

    # --- leitura e manutenção ---

    def query(
        self,
        *,
        severity: str | None = None,
        sensor_id: str | None = None,
        rule_name: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
    ) -> list[Event]:
        clauses: list[str] = []
        params:  list      = []

        # nomes de coluna vêm desta tupla fixa, nunca de quem chama
        for column, value in (
            ("severity",  severity),
            ("sensor_id", sensor_id),
            ("rule_name", rule_name),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)

        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT {_COLUMNS} FROM events {where} "
            f"ORDER BY timestamp DESC, event_id DESC LIMIT ?"
        )
        params.append(limit)

        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._to_event(row) for row in rows]

    def prune(self, before: float) -> int:
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM events WHERE timestamp < ?", (before,))
            return cursor.rowcount

    # --- auxiliares ---

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """
        Conexão curta por operação. O context manager nativo do sqlite3 faz
        commit mas não fecha — e no Windows uma conexão aberta mantém o
        arquivo travado.
        """
        conn = sqlite3.connect(self._path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _to_event(row: tuple) -> Event:
        event_id, timestamp, rule_name, sensor_id, value, unit, severity, score = row
        return Event(
            event_id=event_id,
            timestamp=timestamp,
            rule_name=rule_name,
            sensor_id=sensor_id,
            value=value,
            unit=unit,
            severity=severity,
            anomaly_score=score,
        )
