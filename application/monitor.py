import asyncio
import logging
import signal

from application.pipeline import Pipeline
from core.ports import ExporterPort

logger = logging.getLogger("edgesentinel.monitor")


class MonitorLoop:
    """
    Loop assíncrono principal do edgesentinel.

    Executa todos os pipelines a cada poll_interval_seconds.
    Cada pipeline roda como uma coroutine separada — um sensor
    lento não atrasa os outros.

    Gerencia shutdown gracioso via SIGINT e SIGTERM.
    """

    def __init__(
        self,
        pipelines: list[Pipeline],
        poll_interval_seconds: float = 5.0,
        exporter: ExporterPort | None = None,
    ) -> None:
        self._pipelines = pipelines
        self._interval = poll_interval_seconds
        self._exporter = exporter
        self._running = False

    def start(self) -> None:
        """Entry point síncrono — inicia o event loop do asyncio."""
        asyncio.run(self._run())

    async def _run(self) -> None:
        self._running = True
        self._register_signals()

        if self._exporter is not None:
            self._exporter.start()

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
            logger.info("edgesentinel encerrado.")

    async def _tick(self) -> None:
        """
        Executa todos os pipelines concorrentemente.
        run_in_executor roda o código bloqueante (I/O de /sys, GPIO)
        numa thread separada sem bloquear o event loop.
        """
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(None, pipeline.run_once)
            for pipeline in self._pipelines
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    def _register_signals(self) -> None:
        """
        Registra handlers para SIGINT e SIGTERM.
        No Windows, add_signal_handler não é suportado — usa signal.signal.
        """
        import signal as signal_module
        import platform

        if platform.system() == "Windows":
            # no Windows o asyncio não suporta add_signal_handler
            # signal.signal funciona mas só fora do event loop
            # o KeyboardInterrupt já é capturado no main.py — basta garantir _running
            signal_module.signal(signal_module.SIGINT,  lambda s, f: self._stop())
            signal_module.signal(signal_module.SIGTERM, lambda s, f: self._stop())
        else:
            loop = asyncio.get_event_loop()
            for sig in (signal_module.SIGINT, signal_module.SIGTERM):
                loop.add_signal_handler(sig, self._stop)

    def _stop(self) -> None:
        logger.info("Sinal de encerramento recebido.")
        self._running = False