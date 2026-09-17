from unittest.mock import MagicMock, patch

from application.monitor import MonitorLoop
from core.ports import EventPort


class _StopsAfterFirstTick:
    """Pipeline de teste: roda uma vez e pede o encerramento do loop."""

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

    # handlers de sinal reais trocariam o SIGINT do próprio processo do pytest
    with patch.object(MonitorLoop, "_register_signals"):
        monitor.start()


class TestMonitorEventStoreLifecycle:
    """
    O loop é dono do ciclo de vida do store, como já é do exporter: abre ao
    iniciar e fecha ao encerrar. Fechar é o que grava o que ainda está na
    fila — sem isso, os últimos eventos antes de um Ctrl+C se perdem.
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
        """Event Store desabilitado no config não pode impedir o monitoramento."""
        run_one_tick(event_store=None)
