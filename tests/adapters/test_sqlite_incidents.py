"""
Incidentes no mesmo arquivo SQLite do histórico.

Os eventos apontam para o incidente (events.incident_id), então "um
incidente agrupa N eventos" é uma consulta, não um contador mantido à mão.
"""
import sqlite3
import time

import pytest

from adapters.store.sqlite import SQLiteEventStore
from core.entities import Event
from core.incidents import Incident, IncidentState


@pytest.fixture
def store(tmp_path):
    s = SQLiteEventStore(path=tmp_path / "events.db")
    s.start()
    yield s
    s.close()


def make_incident(**overrides) -> Incident:
    fields = dict(rule_name="alta_temperatura", sensor_id="cpu_temp", severity="warning")
    fields.update(overrides)
    return Incident(**fields)


def make_event(**overrides) -> Event:
    fields = dict(
        rule_name="alta_temperatura",
        sensor_id="cpu_temp",
        value=82.4,
        unit="°C",
        severity="warning",
    )
    fields.update(overrides)
    return Event(**fields)


class TestOpening:

    def test_open_assigns_an_id(self, store):
        opened = store.open_incident(make_incident())

        assert isinstance(opened.incident_id, int)

    def test_open_keeps_everything_else(self, store):
        incident = make_incident(severity="critical", opened_at=1_700_000_000.0)

        opened = store.open_incident(incident)

        assert opened.rule_name == incident.rule_name
        assert opened.sensor_id == incident.sensor_id
        assert opened.severity == "critical"
        assert opened.state is IncidentState.TRIGGERED
        assert opened.opened_at == pytest.approx(1_700_000_000.0)

    def test_open_incidents_lists_them(self, store):
        store.open_incident(make_incident(rule_name="alta_temperatura"))
        store.open_incident(make_incident(rule_name="uso_alto_cpu"))

        assert {i.rule_name for i in store.open_incidents()} == {"alta_temperatura", "uso_alto_cpu"}

    def test_resolved_incidents_are_not_listed(self, store):
        opened = store.open_incident(make_incident())

        store.resolve_incident(opened.incident_id, at=time.time())

        assert store.open_incidents() == []

    def test_a_rule_cannot_have_two_open_incidents(self, store):
        """
        O invariante que faz os disparos se agruparem: enquanto houver um
        incidente aberto para a regra, o banco recusa outro.
        """
        store.open_incident(make_incident())

        with pytest.raises(sqlite3.IntegrityError):
            store.open_incident(make_incident())

    def test_a_new_incident_is_allowed_after_resolving(self, store):
        first = store.open_incident(make_incident())
        store.resolve_incident(first.incident_id, at=time.time())

        second = store.open_incident(make_incident())

        assert second.incident_id != first.incident_id


class TestTransitions:

    def test_acknowledge_records_the_state_and_the_time(self, store):
        opened = store.open_incident(make_incident())

        store.acknowledge_incident(opened.incident_id, at=1_700_000_100.0)

        (current,) = store.open_incidents()
        assert current.state is IncidentState.ACKNOWLEDGED
        assert current.acknowledged_at == pytest.approx(1_700_000_100.0)
        assert current.is_open is True

    def test_resolve_records_the_state_and_the_time(self, store, tmp_path):
        opened = store.open_incident(make_incident())

        store.resolve_incident(opened.incident_id, at=1_700_000_200.0)

        with sqlite3.connect(tmp_path / "events.db") as conn:
            state, resolved_at = conn.execute(
                "SELECT state, resolved_at FROM incidents WHERE incident_id = ?",
                (opened.incident_id,),
            ).fetchone()
        assert state == "resolved"
        assert resolved_at == pytest.approx(1_700_000_200.0)

    def test_transitions_survive_reopening_the_database(self, tmp_path):
        """
        O estado do incidente vive no banco, não na memória do processo: é
        o que faz o ciclo sobreviver a um restart do agente.
        """
        path = tmp_path / "events.db"

        first = SQLiteEventStore(path=path)
        first.start()
        opened = first.open_incident(make_incident())
        first.acknowledge_incident(opened.incident_id, at=1_700_000_100.0)
        first.close()

        second = SQLiteEventStore(path=path)
        second.start()
        try:
            (current,) = second.open_incidents()
            assert current.incident_id == opened.incident_id
            assert current.state is IncidentState.ACKNOWLEDGED
        finally:
            second.close()


class TestEventsPointAtIncidents:

    def test_an_event_keeps_its_incident_id(self, store):
        opened = store.open_incident(make_incident())

        store.append(make_event(incident_id=opened.incident_id))
        store.flush()

        assert store.query()[0].incident_id == opened.incident_id

    def test_an_event_without_an_incident_reads_none(self, store):
        store.append(make_event())
        store.flush()

        assert store.query()[0].incident_id is None

    def test_events_of_one_incident_can_be_counted(self, store):
        opened = store.open_incident(make_incident())

        store.append(make_event(incident_id=opened.incident_id))
        store.append(make_event(incident_id=opened.incident_id))
        store.append(make_event())
        store.flush()

        grouped = [e for e in store.query() if e.incident_id == opened.incident_id]
        assert len(grouped) == 2


class TestSchema:

    def test_the_schema_version_is_two(self, store, tmp_path):
        with sqlite3.connect(tmp_path / "events.db") as conn:
            (version,) = conn.execute("PRAGMA user_version").fetchone()

        assert version == 2

    def test_a_version_one_database_is_migrated_with_its_events(self, tmp_path):
        """
        Bancos da 0.3.0 existem em disco. PRAGMA user_version estava lá
        justamente para que esta migração fosse detectável.
        """
        path = tmp_path / "events.db"
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE events (
                    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp     REAL    NOT NULL,
                    rule_name     TEXT    NOT NULL,
                    sensor_id     TEXT    NOT NULL,
                    value         REAL    NOT NULL,
                    unit          TEXT    NOT NULL,
                    severity      TEXT    NOT NULL,
                    anomaly_score REAL
                );
                PRAGMA user_version = 1;
            """)
            conn.execute(
                "INSERT INTO events (timestamp, rule_name, sensor_id, value, unit, severity)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (1_700_000_000.0, "antiga", "cpu_temp", 91.0, "°C", "critical"),
            )

        store = SQLiteEventStore(path=path)
        store.start()
        try:
            (event,) = store.query()
            assert event.rule_name == "antiga"
            assert event.incident_id is None

            opened = store.open_incident(make_incident())
            assert opened.incident_id is not None
        finally:
            store.close()


class TestRetention:

    def test_prune_removes_resolved_incidents(self, store):
        opened = store.open_incident(make_incident())
        store.resolve_incident(opened.incident_id, at=100.0)

        removed = store.prune(before=500.0)

        assert removed == 1

    def test_prune_keeps_open_incidents_however_old(self, store):
        """Incidente aberto há 40 dias é exatamente o que se quer ver."""
        store.open_incident(make_incident(opened_at=time.time() - 40 * 86400))

        store.prune(before=time.time())

        assert len(store.open_incidents()) == 1
