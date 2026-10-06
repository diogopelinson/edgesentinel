import asyncio
import logging

from application.pipeline import Pipeline
from core.ports import ExporterPort, EventPort

logger = logging.getLogger("edgesentinel.monitor")


class MonitorLoop:
    """
    edgesentinel's main asynchronous loop.

    Runs every pipeline once per poll_interval_seconds. Each pipeline runs as
    its own coroutine — one slow sensor does not delay the others.

    Handles graceful shutdown on SIGINT and SIGTERM.
    """

    def __init__(
        self,
        pipelines: list[Pipeline],
        poll_interval_seconds: float = 5.0,
        exporter: ExporterPort | None = None,
        event_store: EventPort | None = None,
    ) -> None:
        self._pipelines = pipelines
        self._interval = poll_interval_seconds
        self._exporter = exporter
        self._event_store = event_store
        self._running = False

    def start(self) -> None:
        """The synchronous entry point — starts asyncio's event loop."""
        asyncio.run(self._run())

    async def _run(self) -> None:
        self._running = True
        self._register_signals()

        if self._exporter is not None:
            self._exporter.start()

        if self._event_store is not None:
            self._event_store.start()

        logger.info(
            f"edgesentinel iniciado — {len(self._pipelines)} sensor(es), "
            f"intervalo={self._interval}s"
        )

        try:
            while self._running:
                await self._tick()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass
        finally:
            # closing writes whatever is still queued — without this, the
            # last events before a Ctrl+C are lost
            if self._event_store is not None:
                self._event_store.close()
            logger.info("edgesentinel encerrado.")

    async def _tick(self) -> None:
        """
        Runs every pipeline concurrently.
        run_in_executor puts the blocking code (/sys I/O, GPIO) on a separate
        thread without blocking the event loop.
        """
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(None, pipeline.run_once)
            for pipeline in self._pipelines
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    def _register_signals(self) -> None:
        """
        Registers handlers for SIGINT and SIGTERM.
        On Windows add_signal_handler is unsupported — signal.signal is used.
        """
        import signal as signal_module
        import platform

        if platform.system() == "Windows":
            # on Windows asyncio does not support add_signal_handler
            # signal.signal works, but only outside the event loop
            # KeyboardInterrupt is already caught in main.py — only _running matters
            signal_module.signal(signal_module.SIGINT,  lambda s, f: self._stop())
            signal_module.signal(signal_module.SIGTERM, lambda s, f: self._stop())
        else:
            loop = asyncio.get_event_loop()
            for sig in (signal_module.SIGINT, signal_module.SIGTERM):
                loop.add_signal_handler(sig, self._stop)

    def _stop(self) -> None:
        logger.info("Sinal de encerramento recebido.")
        self._running = False
