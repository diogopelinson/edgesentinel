import logging
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

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

-- uma regra tem no máximo um incidente aberto: é o banco que garante o
-- agrupamento dos disparos, não o engine
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

# sinaliza para a thread de escrita que não virá mais nada
_STOP = object()


class SQLiteEventStore(EventPort, IncidentPort):
    """
    Histórico de regras disparadas e ciclo de vida dos incidentes, no mesmo
    arquivo SQLite local.

    append() só enfileira; uma thread dedicada grava em lote. O pipeline roda
    em run_in_executor, num pool limitado — num cartão SD, um fsync pode
    travar por centenas de milissegundos, e esse atraso não pode segurar o
    worker que está lendo sensores.

    Com a fila cheia o evento é descartado com aviso: perder um registro do
    histórico é preferível a atrasar o próximo alerta.

    Incidentes vão pelo caminho síncrono, sem fila: são raros (uma abertura
    e um fechamento por episódio, não um por leitura) e a decisão seguinte
    depende de ler o que acabou de ser escrito — inclusive um reconhecimento
    feito por outro processo.
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
             e.unit, e.severity, e.anomaly_score, e.incident_id)
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
        """
        Remove eventos antigos e incidentes já resolvidos. Incidente aberto
        nunca é removido, por velho que seja: é justamente o que se quer ver.
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

    # --- incidentes (IncidentPort) ---

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
    def _migrate(conn: sqlite3.Connection) -> None:
        """
        Acerta bancos criados por versões anteriores. O _SCHEMA cria o que
        falta, mas não altera tabela que já existe: um banco da 0.3.0 tem a
        tabela events sem a coluna incident_id.
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
