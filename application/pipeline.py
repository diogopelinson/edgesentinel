import time
import logging

from core.ports import SensorPort, InferencePort
from application.engine import RuleEngine
from adapters.exporter.prometheus import PrometheusExporter

logger = logging.getLogger("edgesentinel.pipeline")


class Pipeline:

    def __init__(
        self,
        sensor: SensorPort,
        engine: RuleEngine,
        inference: InferencePort | None = None,
        exporter: PrometheusExporter | None = None,
    ) -> None:
        self._sensor = sensor
        self._engine = engine
        self._inference = inference
        self._exporter = exporter

    def run_once(self) -> None:
        pipeline_start = time.monotonic()

        try:
            reading = self._sensor.read()
        except Exception as e:
            logger.error(f"Falha ao ler sensor: {e}")
            return

        score = None
        if self._inference is not None:
            try:
                infer_start = time.monotonic()
                score = self._inference.predict(reading)
                infer_duration = time.monotonic() - infer_start

                if self._exporter is not None:
                    self._exporter.record_inference_latency(
                        model_id=score.model_id,
                        duration=infer_duration,
                    )
            except Exception as e:
                logger.error(f"Falha na inferência: {e}")

        self._engine.evaluate(reading, score)

        if self._exporter is not None:
            self._exporter.record(reading, score)
            self._exporter.record_pipeline_latency(
                sensor_id=reading.sensor_id,
                duration=time.monotonic() - pipeline_start,
            )