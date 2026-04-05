from __future__ import annotations
import logging
from core.ports import ExporterPort
from core.entities import SensorReading, AnomalyScore

logger = logging.getLogger("edgesentinel.exporter.otel")


class OTelExporter(ExporterPort):
    """
    Exportador OpenTelemetry — instrumenta uma vez, exporta pra qualquer backend.

    Backends suportados via config:
        otlp        → OTel Collector (Grafana, Datadog, Jaeger, etc)
        prometheus  → endpoint /metrics (compatibilidade com Prometheus)

    O OTel Collector decide pra onde os dados vão — o edgesentinel
    não precisa saber nada sobre o backend final.
    """

    def __init__(
        self,
        backend: str = "otlp",
        endpoint: str = "http://localhost:4317",
        port: int = 8000,
        service_name: str = "edgesentinel",
    ) -> None:
        self._backend      = backend
        self._endpoint     = endpoint
        self._port         = port
        self._service_name = service_name
        self._started      = False

        # métricas — inicializadas em start()
        self._sensor_gauge     = None
        self._anomaly_gauge    = None
        self._anomaly_counter  = None
        self._infer_histogram  = None
        self._pipeline_histogram = None

    def start(self) -> None:
        if self._started:
            return

        try:
            from opentelemetry import metrics
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        except ImportError:
            raise ImportError(
                "opentelemetry-sdk não instalado. "
                "Execute: pip install opentelemetry-sdk"
            )

        resource = Resource(attributes={SERVICE_NAME: self._service_name})
        readers  = self._build_readers()

        provider = MeterProvider(resource=resource, metric_readers=readers)
        metrics.set_meter_provider(provider)

        meter = metrics.get_meter("edgesentinel")
        self._setup_instruments(meter)

        self._started = True
        logger.info(
            f"OTel exporter iniciado — backend={self._backend} "
            f"service={self._service_name}"
        )

    def record(
        self,
        reading: SensorReading,
        score: AnomalyScore | None = None,
    ) -> None:
        if not self._started:
            return

        labels = {
            "sensor_id":   reading.sensor_id,
            "sensor_name": reading.name,
            "unit":        reading.unit,
        }

        self._sensor_gauge.set(reading.value, labels)

        if score is not None:
            score_labels = {
                "sensor_id": score.reading.sensor_id,
                "model_id":  score.model_id,
            }
            self._anomaly_gauge.set(score.score, score_labels)

            if score.is_anomaly:
                self._anomaly_counter.add(1, score_labels)

    def record_inference_latency(self, model_id: str, duration: float) -> None:
        if self._infer_histogram:
            self._infer_histogram.record(duration, {"model_id": model_id})

    def record_pipeline_latency(self, sensor_id: str, duration: float) -> None:
        if self._pipeline_histogram:
            self._pipeline_histogram.record(duration, {"sensor_id": sensor_id})

    # --- métodos privados ---

    def _build_readers(self) -> list:
        readers = []

        if self._backend == "otlp":
            readers.append(self._build_otlp_reader())
        elif self._backend == "prometheus":
            readers.append(self._build_prometheus_reader())
        elif self._backend == "both":
            readers.append(self._build_otlp_reader())
            readers.append(self._build_prometheus_reader())
        else:
            raise ValueError(
                f"Backend OTel desconhecido: '{self._backend}'. "
                f"Use: otlp | prometheus | both"
            )

        return readers

    def _build_otlp_reader(self):
        try:
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
        except ImportError:
            raise ImportError(
                "opentelemetry-exporter-otlp-proto-grpc não instalado.\n"
                "Execute: pip install opentelemetry-exporter-otlp-proto-grpc"
            )

        exporter = OTLPMetricExporter(endpoint=self._endpoint, insecure=True)
        reader   = PeriodicExportingMetricReader(exporter, export_interval_millis=5000)
        logger.info(f"OTLP reader configurado → {self._endpoint}")
        return reader

    def _build_prometheus_reader(self):
        try:
            from opentelemetry.exporter.prometheus import PrometheusMetricReader
            import prometheus_client
        except ImportError:
            raise ImportError(
                "opentelemetry-exporter-prometheus não instalado.\n"
                "Execute: pip install opentelemetry-exporter-prometheus"
            )

        prometheus_client.start_http_server(port=self._port)
        reader = PrometheusMetricReader()
        logger.info(f"Prometheus reader configurado → http://0.0.0.0:{self._port}/metrics")
        return reader

    def _setup_instruments(self, meter) -> None:
        self._sensor_gauge = meter.create_gauge(
            name="edgesentinel.sensor.value",
            description="Valor atual lido do sensor",
            unit="1",
        )

        self._anomaly_gauge = meter.create_gauge(
            name="edgesentinel.anomaly.score",
            description="Score de anomalia do modelo ML (0.0 a 1.0)",
            unit="1",
        )

        self._anomaly_counter = meter.create_counter(
            name="edgesentinel.anomaly.total",
            description="Total de anomalias detectadas",
            unit="1",
        )

        self._infer_histogram = meter.create_histogram(
            name="edgesentinel.inference.latency",
            description="Duração da inferência em segundos",
            unit="s",
        )

        self._pipeline_histogram = meter.create_histogram(
            name="edgesentinel.pipeline.latency",
            description="Duração do ciclo completo sense→infer→act",
            unit="s",
        )