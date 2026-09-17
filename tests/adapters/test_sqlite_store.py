import logging
import time

import pytest

from adapters.store.sqlite import SQLiteEventStore
from core.entities import Event


@pytest.fixture
def store(tmp_path):
    """Store aberto num banco descartável, encerrado ao fim do teste."""
    s = SQLiteEventStore(path=tmp_path / "events.db")
    s.start()
    yield s
    s.close()


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


def append_and_wait(store: SQLiteEventStore, *events: Event) -> None:
    for event in events:
        store.append(event)
    store.flush()


class TestPersistence:

    def test_creates_the_database_on_start(self, tmp_path):
        path = tmp_path / "nested" / "events.db"
        store = SQLiteEventStore(path=path)

        store.start()
        store.close()

        assert path.exists()

    def test_round_trips_every_field(self, store):
        append_and_wait(store, make_event(
            rule_name="temperatura_critica",
            sensor_id="cpu_temp",
            value=91.2,
            unit="°C",
            severity="critical",
            anomaly_score=0.93,
            timestamp=1_700_000_000.5,
        ))

        stored = store.query()[0]

        assert stored.rule_name     == "temperatura_critica"
        assert stored.sensor_id     == "cpu_temp"
        assert stored.value         == pytest.approx(91.2)
        assert stored.unit          == "°C"
        assert stored.severity      == "critical"
        assert stored.anomaly_score == pytest.approx(0.93)
        assert stored.timestamp     == pytest.approx(1_700_000_000.5)

    def test_assigns_an_event_id(self, store):
        append_and_wait(store, make_event(), make_event())

        ids = [e.event_id for e in store.query()]

        assert all(i is not None for i in ids)
        assert len(set(ids)) == 2

    def test_preserves_a_missing_anomaly_score_as_none(self, store):
        """Regra de threshold dispara sem inferência — NULL não pode virar 0.0."""
        append_and_wait(store, make_event(anomaly_score=None))

        assert store.query()[0].anomaly_score is None

    def test_survives_reopening_the_database(self, tmp_path):
        path = tmp_path / "events.db"

        first = SQLiteEventStore(path=path)
        first.start()
        append_and_wait(first, make_event(rule_name="antes_do_restart"))
        first.close()

        second = SQLiteEventStore(path=path)
        second.start()
        try:
            assert second.query()[0].rule_name == "antes_do_restart"
        finally:
            second.close()


class TestQuery:

    def test_returns_newest_first(self, store):
        append_and_wait(
            store,
            make_event(rule_name="antiga", timestamp=1_000.0),
            make_event(rule_name="nova",   timestamp=2_000.0),
        )

        assert [e.rule_name for e in store.query()] == ["nova", "antiga"]

    def test_filters_by_severity(self, store):
        append_and_wait(
            store,
            make_event(rule_name="aviso",  severity="warning"),
            make_event(rule_name="critica", severity="critical"),
        )

        found = store.query(severity="critical")

        assert [e.rule_name for e in found] == ["critica"]

    def test_filters_by_sensor_id(self, store):
        append_and_wait(
            store,
            make_event(sensor_id="cpu_temp"),
            make_event(sensor_id="memory_usage"),
        )

        found = store.query(sensor_id="memory_usage")

        assert [e.sensor_id for e in found] == ["memory_usage"]

    def test_filters_by_rule_name(self, store):
        append_and_wait(
            store,
            make_event(rule_name="alta_temperatura"),
            make_event(rule_name="uso_alto_cpu"),
        )

        found = store.query(rule_name="uso_alto_cpu")

        assert [e.rule_name for e in found] == ["uso_alto_cpu"]

    def test_filters_by_time_window_inclusively(self, store):
        append_and_wait(
            store,
            make_event(rule_name="antes",  timestamp=100.0),
            make_event(rule_name="dentro", timestamp=200.0),
            make_event(rule_name="depois", timestamp=300.0),
        )

        found = store.query(since=200.0, until=300.0)

        assert [e.rule_name for e in found] == ["depois", "dentro"]

    def test_combines_filters(self, store):
        append_and_wait(
            store,
            make_event(sensor_id="cpu_temp", severity="critical", timestamp=100.0),
            make_event(sensor_id="cpu_temp", severity="warning",  timestamp=200.0),
            make_event(sensor_id="memory_usage", severity="critical", timestamp=300.0),
        )

        found = store.query(sensor_id="cpu_temp", severity="critical")

        assert len(found) == 1
        assert found[0].timestamp == pytest.approx(100.0)

    def test_honours_the_limit(self, store):
        append_and_wait(store, *[make_event(timestamp=float(i)) for i in range(10)])

        assert len(store.query(limit=3)) == 3

    def test_returns_empty_list_when_nothing_matches(self, store):
        append_and_wait(store, make_event(severity="warning"))

        assert store.query(severity="critical") == []


class TestRetention:

    def test_prune_removes_only_older_events(self, store):
        append_and_wait(
            store,
            make_event(rule_name="velha", timestamp=100.0),
            make_event(rule_name="nova",  timestamp=900.0),
        )

        removed = store.prune(before=500.0)

        assert removed == 1
        assert [e.rule_name for e in store.query()] == ["nova"]

    def test_start_prunes_beyond_the_retention_window(self, tmp_path):
        path = tmp_path / "events.db"
        now  = time.time()

        first = SQLiteEventStore(path=path, retention_days=30)
        first.start()
        append_and_wait(
            first,
            make_event(rule_name="dentro_da_janela", timestamp=now - 10 * 86400),
            make_event(rule_name="expirada",         timestamp=now - 40 * 86400),
        )
        first.close()

        second = SQLiteEventStore(path=path, retention_days=30)
        second.start()
        try:
            assert [e.rule_name for e in second.query()] == ["dentro_da_janela"]
        finally:
            second.close()


class TestNonBlockingWrites:
    """
    O pipeline roda em run_in_executor (application/monitor.py:66), num pool
    limitado. Um stall de escrita no cartão SD não pode segurar esse worker,
    senão o tick estoura o poll_interval.
    """

    def test_append_does_not_block_when_the_queue_is_full(self, tmp_path, caplog):
        # sem start(), nada drena a fila — simula escrita travada
        store = SQLiteEventStore(path=tmp_path / "events.db", queue_size=2)

        with caplog.at_level(logging.WARNING, logger="edgesentinel.store"):
            started = time.monotonic()
            for _ in range(20):
                store.append(make_event())
            elapsed = time.monotonic() - started

        assert elapsed < 0.5
        assert "descartado" in caplog.text

    def test_close_flushes_what_is_still_queued(self, tmp_path):
        path  = tmp_path / "events.db"
        store = SQLiteEventStore(path=path)
        store.start()

        for i in range(50):
            store.append(make_event(timestamp=float(i)))
        store.close()

        reopened = SQLiteEventStore(path=path)
        reopened.start()
        try:
            assert len(reopened.query(limit=100)) == 50
        finally:
            reopened.close()
