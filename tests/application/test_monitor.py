from unittest.mock import MagicMock, patch

from application.monitor import MonitorLoop
from core.ports import EventPort


class _StopsAfterFirstTick:
    """Test pipeline: runs once and asks the loop to shut down."""

    def __init__(self) -> None:
        self.monitor: MonitorLoop | None = None

    def run_once(self) -> None:
        self.monitor._stop()


def run_one_tick(event_store: EventPort | None) -> None:
    pipeline = _StopsAfterFirstTick()
    monitor  = MonitorLoop(
        pipelines=[pipeline],
        poll_interval_seconds=0,
        event_store=event_store,
    )
    pipeline.monitor = monitor

    # real signal handlers would replace the SIGINT of pytest's own process
    with patch.object(MonitorLoop, "_register_signals"):
        monitor.start()


class TestMonitorEventStoreLifecycle:
    """
    The loop owns the lifecycle of the store, as it already does the exporter's:
    it opens on start and closes on shutdown. Closing is what writes what is
    still in the queue — without it, the last events before a Ctrl+C are lost.
    """

    def test_starts_the_event_store(self):
        store = MagicMock(spec=EventPort)

        run_one_tick(store)

        store.start.assert_called_once()

    def test_closes_the_event_store_on_shutdown(self):
        store = MagicMock(spec=EventPort)

        run_one_tick(store)

        store.close.assert_called_once()

    def test_starts_before_it_closes(self):
        store = MagicMock(spec=EventPort)

        run_one_tick(store)

        assert [c[0] for c in store.method_calls] == ["start", "close"]

    def test_runs_without_an_event_store(self):
        """An Event Store disabled in the config must not prevent monitoring."""
        run_one_tick(event_store=None)
