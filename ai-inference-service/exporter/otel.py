from __future__ import annotations
import logging

logger = logging.getLogger("ai_service.exporter")


class ServiceExporter:
    """Exporta métricas do AI Service via OTel para o mesmo Collector."""

    def __init__(
        self,
        endpoint: str = "http://edgesentinel-otel-collector:4317",
        service_name: str = "ai-inference-service",
    ) -> None:
        self._endpoint     = endpoint
        self._service_name = service_name
        self._inference_counter    = None
        self._latency_histogram    = None
        self._detections_counter   = None

    def start(self) -> None:
        try:
            from opentelemetry import metrics
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

            resource = Resource(attributes={SERVICE_NAME: self._service_name})
            exporter = OTLPMetricExporter(endpoint=self._endpoint, insecure=True)
            reader   = PeriodicExportingMetricReader(exporter, export_interval_millis=5000)
            provider = MeterProvider(resource=resource, metric_readers=[reader])
            metrics.set_meter_provider(provider)

            meter = metrics.get_meter("ai-inference-service")
            self._inference_counter  = meter.create_counter(
                "ai_service.inference.total",
                description="Total de inferências executadas",
            )
            self._latency_histogram  = meter.create_histogram(
                "ai_service.inference.latency_ms",
                description="Latência de inferência em ms",
                unit="ms",
            )
            self._detections_counter = meter.create_counter(
                "ai_service.detections.total",
                description="Total de detecções retornadas",
            )
            logger.info(f"OTel exporter iniciado → {self._endpoint}")
        except Exception as e:
            logger.warning(f"OTel não disponível: {e}. Métricas desabilitadas.")

    def record_inference(
        self,
        model_id: str,
        latency_ms: float,
        detections: int,
    ) -> None:
        labels = {"model_id": model_id}
        if self._inference_counter:
            self._inference_counter.add(1, labels)
        if self._latency_histogram:
            self._latency_histogram.record(latency_ms, labels)
        if self._detections_counter:
            self._detections_counter.add(detections, labels)