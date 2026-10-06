import logging
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator

from dataclasses import replace

from core.entities import Event
from core.incidents import Incident, IncidentState
from core.ports import EventPort, IncidentPort

logger = logging.getLogger("edgesentinel.store")

_SCHEMA_VERSION  = 2
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
    anomaly_score REAL,
    incident_id   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp);
CREATE INDEX IF NOT EXISTS idx_events_severity  ON events (severity, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_sensor    ON events (sensor_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_rule      ON events (rule_name, timestamp);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name       TEXT    NOT NULL,
    sensor_id       TEXT    NOT NULL,
    severity        TEXT    NOT NULL,
    state           TEXT    NOT NULL,
    opened_at       REAL    NOT NULL,
    acknowledged_at REAL,
    resolved_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_incidents_state ON incidents (state, opened_at);

-- a rule has at most one open incident: it is the database that guarantees the
-- grouping of the firings, not the engine
CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_one_open_per_rule
    ON incidents (rule_name) WHERE state != 'resolved';
"""

_COLUMNS = (
    "event_id, timestamp, rule_name, sensor_id, value, unit, severity, "
    "anomaly_score, incident_id"
)

_INSERT = (
    "INSERT INTO events (timestamp, rule_name, sensor_id, value, unit, severity, "
    "anomaly_score, incident_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)

_INCIDENT_COLUMNS = (
    "incident_id, rule_name, sensor_id, severity, state, opened_at, "
    "acknowledged_at, resolved_at"
)

_INSERT_INCIDENT = (
    "INSERT INTO incidents (rule_name, sensor_id, severity, state, opened_at, "
    "acknowledged_at, resolved_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
)

# signals to the writer thread that nothing else is coming
_STOP = object()


class SQLiteEventStore(EventPort, IncidentPort):
    """
    History of fired rules and the incident lifecycle, in the same local
    SQLite file.

    append() only enqueues; a dedicated thread writes in batches. The pipeline
    runs in run_in_executor, on a bounded pool — on an SD card an fsync can
    block for hundreds of milliseconds, and that delay cannot hold up the
    worker that is reading sensors.

    With the queue full the event is dropped with a warning: losing one record
    of the history is preferable to delaying the next alert.

    Incidents go down the synchronous path, with no queue: they are rare (one
    opening and one closing per episode, not one per reading) and the next
    decision depends on reading what has just been written — including an
    acknowledgement made by another process.
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

    # --- lifecycle ---

    def start(self) -> None:
        if self._writer is not None:
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            # WAL lets query() read while the writer thread is writing
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            self._migrate(conn)
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

    # --- writing ---

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
        Waits for the queue to drain. Returns False if the deadline runs out
        first. Not part of EventPort: it exists for deterministic tests.
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
        """Writer thread loop. The connection belongs to this thread alone."""
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
             e.unit, e.severity, e.anomaly_score, e.incident_id)
            for e in events
        ])
        conn.commit()

    # --- reading and maintenance ---

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

        # column names come from this fixed tuple, never from the caller
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
        """
        Removes old events and already-resolved incidents. An open incident is
        never removed, however old it is: it is exactly what one wants to see.
        """
        with self._connection() as conn:
            events = conn.execute(
                "DELETE FROM events WHERE timestamp < ?", (before,)
            ).rowcount
            incidents = conn.execute(
                "DELETE FROM incidents WHERE state = ? AND resolved_at < ?",
                (IncidentState.RESOLVED.value, before),
            ).rowcount
            return events + incidents

    # --- incidents (IncidentPort) ---

    def open_incident(self, incident: Incident) -> Incident:
        with self._connection() as conn:
            cursor = conn.execute(_INSERT_INCIDENT, (
                incident.rule_name,
                incident.sensor_id,
                incident.severity,
                incident.state.value,
                incident.opened_at,
                incident.acknowledged_at,
                incident.resolved_at,
            ))
            return replace(incident, incident_id=cursor.lastrowid)

    def acknowledge_incident(self, incident_id: int, at: float) -> None:
        self._set_state(incident_id, IncidentState.ACKNOWLEDGED, acknowledged_at=at)

    def resolve_incident(self, incident_id: int, at: float) -> None:
        self._set_state(incident_id, IncidentState.RESOLVED, resolved_at=at)

    def open_incidents(self) -> list[Incident]:
        sql = (
            f"SELECT {_INCIDENT_COLUMNS} FROM incidents WHERE state != ? "
            f"ORDER BY opened_at, incident_id"
        )
        with self._connection() as conn:
            rows = conn.execute(sql, (IncidentState.RESOLVED.value,)).fetchall()

        return [self._to_incident(row) for row in rows]

    # --- incident queries (beyond the port: the terminal is what uses them) ---

    def incident(self, incident_id: int) -> Incident | None:
        """
        Reads one incident by id, or None. Does not raise: the caller is the
        one that knows what to tell the operator about an id that does not
        exist.
        """
        sql = f"SELECT {_INCIDENT_COLUMNS} FROM incidents WHERE incident_id = ?"
        with self._connection() as conn:
            row = conn.execute(sql, (incident_id,)).fetchone()

        return self._to_incident(row) if row else None

    def incidents(
        self,
        *,
        include_resolved: bool = False,
        severity: str | None = None,
        rule_name: str | None = None,
        since: float | None = None,
        limit: int = 20,
    ) -> list[Incident]:
        """
        Listing for the terminal, most recent first. open_incidents() is the
        engine's view: no filter and no limit, because it needs all of them.
        """
        clausulas: list[str] = []
        parametros: list[object] = []

        if not include_resolved:
            clausulas.append("state != ?")
            parametros.append(IncidentState.RESOLVED.value)
        if severity:
            clausulas.append("severity = ?")
            parametros.append(severity)
        if rule_name:
            clausulas.append("rule_name = ?")
            parametros.append(rule_name)
        if since is not None:
            clausulas.append("opened_at >= ?")
            parametros.append(since)

        where = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
        sql = (
            f"SELECT {_INCIDENT_COLUMNS} FROM incidents {where} "
            f"ORDER BY opened_at DESC, incident_id DESC LIMIT ?"
        )
        with self._connection() as conn:
            rows = conn.execute(sql, (*parametros, limit)).fetchall()

        return [self._to_incident(row) for row in rows]

    def firings(self, incident_ids: list[int]) -> dict[int, int]:
        """
        How many events each incident grouped, in a single query — one per
        table row would be N queries for a listing of N.
        """
        if not incident_ids:
            return {}

        marcadores = ", ".join("?" * len(incident_ids))
        sql = (
            f"SELECT incident_id, COUNT(*) FROM events "
            f"WHERE incident_id IN ({marcadores}) GROUP BY incident_id"
        )
        with self._connection() as conn:
            contagem = dict(conn.execute(sql, incident_ids).fetchall())

        return {incident_id: contagem.get(incident_id, 0) for incident_id in incident_ids}

    def _set_state(
        self,
        incident_id: int,
        state: IncidentState,
        acknowledged_at: float | None = None,
        resolved_at: float | None = None,
    ) -> None:
        column = "acknowledged_at" if acknowledged_at is not None else "resolved_at"
        stamp  = acknowledged_at if acknowledged_at is not None else resolved_at

        with self._connection() as conn:
            conn.execute(
                f"UPDATE incidents SET state = ?, {column} = ? WHERE incident_id = ?",
                (state.value, stamp, incident_id),
            )

    # --- helpers ---

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """
        A short-lived connection per operation. sqlite3's native context
        manager commits but does not close — and on Windows an open connection
        keeps the file locked.
        """
        conn = sqlite3.connect(self._path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """
        Fixes up databases created by earlier versions. _SCHEMA creates what
        is missing, but does not alter a table that already exists: a 0.3.0
        database has the events table without the incident_id column.
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
        if "incident_id" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN incident_id INTEGER")
            logger.info("Banco migrado: events.incident_id adicionada.")

    @staticmethod
    def _to_event(row: tuple) -> Event:
        (event_id, timestamp, rule_name, sensor_id, value,
         unit, severity, score, incident_id) = row
        return Event(
            event_id=event_id,
            timestamp=timestamp,
            rule_name=rule_name,
            sensor_id=sensor_id,
            value=value,
            unit=unit,
            severity=severity,
            anomaly_score=score,
            incident_id=incident_id,
        )

    @staticmethod
    def _to_incident(row: tuple) -> Incident:
        (incident_id, rule_name, sensor_id, severity, state,
         opened_at, acknowledged_at, resolved_at) = row
        return Incident(
            incident_id=incident_id,
            rule_name=rule_name,
            sensor_id=sensor_id,
            severity=severity,
            state=IncidentState(state),
            opened_at=opened_at,
            acknowledged_at=acknowledged_at,
            resolved_at=resolved_at,
        )
