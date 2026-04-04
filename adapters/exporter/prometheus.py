import time
import logging
import threading

import prometheus_client

from core.ports import ExporterPort
from core.entities import SensorReading, AnomalyScore
from adapters.exporter.metrics import (
    SENSOR_VALUE,
    ANOMALY_SCORE,
    ANOMALY_TOTAL,
    INFERENCE_LATENCY,
    PIPELINE_LATENCY,
)

logger = logging.getLogger("edgesentinel.exporter")


class PrometheusExporter(ExporterPort):
    """
    Exporta métricas do edgesentinel para o Prometheus.
    Sobe um servidor HTTP na porta configurada que responde
    ao scrape do Prometheus em /metrics.
    """

    def __init__(self, port: int = 8000) -> None:
        self._port = port
        self._started = False

    def start(self) -> None:
        """
        Inicia o servidor HTTP em background.
        Chamado uma vez pelo MonitorLoop na inicialização.
        """
        if self._started:
            return

        # disable_created_metrics evita métricas _created
        # que poluem o Grafana sem agregar valor
        prometheus_client.REGISTRY.unregister(
            prometheus_client.GC_COLLECTOR
        )
        prometheus_client.REGISTRY.unregister(
            prometheus_client.PLATFORM_COLLECTOR
        )
        prometheus_client.REGISTRY.unregister(
            prometheus_client.PROCESS_COLLECTOR
        )

        prometheus_client.start_http_server(port=self._port)
        self._started = True
        logger.info(f"Prometheus exporter ativo em http://0.0.0.0:{self._port}/metrics")

    def record(
        self,
        reading: SensorReading,
        score: AnomalyScore | None = None,
    ) -> None:
        """
        Atualiza as métricas com os dados de uma leitura.
        Chamado pelo Pipeline após cada ciclo completo.
        """
        self._record_reading(reading)

        if score is not None:
            self._record_score(score)

    def record_inference_latency(self, model_id: str, duration: float) -> None:
        INFERENCE_LATENCY.labels(model_id=model_id).observe(duration)

    def record_pipeline_latency(self, sensor_id: str, duration: float) -> None:
        PIPELINE_LATENCY.labels(sensor_id=sensor_id).observe(duration)

    # --- métodos privados ---

    def _record_reading(self, reading: SensorReading) -> None:
        SENSOR_VALUE.labels(
            sensor_id=reading.sensor_id,
            sensor_name=reading.name,
            unit=reading.unit,
        ).set(reading.value)

    def _record_score(self, score: AnomalyScore) -> None:
        ANOMALY_SCORE.labels(
            sensor_id=score.reading.sensor_id,
            model_id=score.model_id,
        ).set(score.score)

        if score.is_anomaly:
            ANOMALY_TOTAL.labels(
                sensor_id=score.reading.sensor_id,
                model_id=score.model_id,
            ).inc()