"""
Incidents in the same SQLite file as the history.

The events point at the incident (events.incident_id), so "one incident groups
N events" is a query, not a counter kept by hand.
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
        The invariant that makes the firings group together: as long as there
        is an open incident for the rule, the database refuses another.
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
        The incident's state lives in the database, not in the process's
        memory: that is what makes the cycle survive an agent restart.
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


class TestQuerying:
    """
    The operator needs to find an incident in order to acknowledge it.
    open_incidents() serves the engine — only the open ones, with no filter;
    the terminal needs a read by id, a filter and a count of firings.
    """

    def test_reads_one_incident_by_id(self, store):
        aberto = store.open_incident(make_incident())

        lido = store.incident(aberto.incident_id)

        assert lido == aberto

    def test_an_unknown_id_reads_none(self, store):
        """The caller decides what to tell the operator — the store does not raise."""
        assert store.incident(9999) is None

    def test_lists_only_open_incidents_by_default(self, store):
        aberto = store.open_incident(make_incident(rule_name="aberta"))
        resolvido = store.open_incident(make_incident(rule_name="resolvida"))
        store.resolve_incident(resolvido.incident_id, at=time.time())

        listados = [i.rule_name for i in store.incidents()]

        assert listados == ["aberta"]
        assert aberto.rule_name in listados

    def test_include_resolved_lists_everything(self, store):
        store.open_incident(make_incident(rule_name="aberta"))
        resolvido = store.open_incident(make_incident(rule_name="resolvida"))
        store.resolve_incident(resolvido.incident_id, at=time.time())

        listados = {i.rule_name for i in store.incidents(include_resolved=True)}

        assert listados == {"aberta", "resolvida"}

    def test_filters_by_severity_and_by_rule(self, store):
        store.open_incident(make_incident(rule_name="temp", severity="critical"))
        store.open_incident(make_incident(rule_name="cpu", severity="warning"))

        criticos = [i.rule_name for i in store.incidents(severity="critical")]
        por_regra = [i.rule_name for i in store.incidents(rule_name="cpu")]

        assert criticos == ["temp"]
        assert por_regra == ["cpu"]

    def test_filters_by_when_it_opened(self, store):
        agora = time.time()
        store.open_incident(make_incident(rule_name="antiga", opened_at=agora - 7200))
        store.open_incident(make_incident(rule_name="recente", opened_at=agora - 60))

        recentes = [i.rule_name for i in store.incidents(since=agora - 600)]

        assert recentes == ["recente"]

    def test_the_newest_come_first_and_the_limit_is_respected(self, store):
        agora = time.time()
        for minutos in (30, 20, 10):
            store.open_incident(make_incident(rule_name=f"r{minutos}", opened_at=agora - minutos * 60))

        listados = [i.rule_name for i in store.incidents(limit=2)]

        assert listados == ["r10", "r20"]

    def test_counts_the_firings_of_several_incidents_at_once(self, store):
        """
        One query, not one per row of the table: the terminal's listing shows
        the firing count of each incident.
        """
        um = store.open_incident(make_incident(rule_name="um"))
        dois = store.open_incident(make_incident(rule_name="dois"))
        for _ in range(3):
            store.append(make_event(incident_id=um.incident_id))
        store.append(make_event(incident_id=dois.incident_id))
        assert store.flush()

        contagem = store.firings([um.incident_id, dois.incident_id])

        assert contagem == {um.incident_id: 3, dois.incident_id: 1}

    def test_an_incident_with_no_firing_counts_zero(self, store):
        sozinho = store.open_incident(make_incident())

        assert store.firings([sozinho.incident_id]) == {sozinho.incident_id: 0}

    def test_counting_nothing_asks_the_database_nothing(self, store):
        assert store.firings([]) == {}


class TestSchema:

    def test_the_schema_version_is_two(self, store, tmp_path):
        with sqlite3.connect(tmp_path / "events.db") as conn:
            (version,) = conn.execute("PRAGMA user_version").fetchone()

        assert version == 2

    def test_a_version_one_database_is_migrated_with_its_events(self, tmp_path):
        """
        0.3.0 databases exist on disk. PRAGMA user_version was there precisely
        so that this migration would be detectable.
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
            # a recent date: start() applies retention, and a 2023 event
            # would be pruned before the migration could be checked
            conn.execute(
                "INSERT INTO events (timestamp, rule_name, sensor_id, value, unit, severity)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (time.time() - 60, "antiga", "cpu_temp", 91.0, "°C", "critical"),
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
        """An incident open for 40 days is exactly what one wants to see."""
        store.open_incident(make_incident(opened_at=time.time() - 40 * 86400))

        store.prune(before=time.time())

        assert len(store.open_incidents()) == 1
