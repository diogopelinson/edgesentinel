import contextlib
import logging

import prometheus_client

from core.ports import ExporterPort, IncidentMetricsPort, IncidentPort
from core.entities import SensorReading, AnomalyScore
from core.incidents import Incident
from adapters.exporter.incidents import OpenIncidentsCollector
from adapters.exporter.metrics import (
    SENSOR_VALUE,
    ANOMALY_SCORE,
    ANOMALY_TOTAL,
    INCIDENT_DURATION,
    INCIDENTS_TOTAL,
    INFERENCE_LATENCY,
    PIPELINE_LATENCY,
)

logger = logging.getLogger("edgesentinel.exporter")


class PrometheusExporter(ExporterPort, IncidentMetricsPort):
    """
    Exporta métricas do edgesentinel para o Prometheus.
    Sobe um servidor HTTP na porta configurada que responde
    ao scrape do Prometheus em /metrics.

    Com uma loja de incidentes em mãos, também publica quantos estão abertos
    agora — número que é lido dali a cada scrape, não acumulado aqui.
    """

    def __init__(self, port: int = 8000, incidents: IncidentPort | None = None) -> None:
        self._port = port
        self._incidents = incidents
        self._started = False

    def start(self) -> None:
        """
        Inicia o servidor HTTP em background.
        Chamado uma vez pelo MonitorLoop na inicialização.
        """
        if self._started:
            return

        self._unregister_defaults()

        # o gauge de abertos é lido da loja no scrape. Sem event_store não
        # existe incidente, e registrar aqui publicaria um gauge que nunca
        # sai de vazio
        if self._incidents is not None:
            prometheus_client.REGISTRY.register(
                OpenIncidentsCollector(self._incidents)
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

    def record_incident_opened(self, incident: Incident) -> None:
        INCIDENTS_TOTAL.labels(
            rule=incident.rule_name,
            severity=incident.severity,
            transition="opened",
        ).inc()

    def record_incident_resolved(
        self, incident: Incident, duration_seconds: float,
    ) -> None:
        INCIDENTS_TOTAL.labels(
            rule=incident.rule_name,
            severity=incident.severity,
            transition="resolved",
        ).inc()
        INCIDENT_DURATION.labels(severity=incident.severity).observe(
            # o relógio do dispositivo anda para trás quando o NTP acerta.
            # Duração negativa somada aqui corrompe o quantil de todos os
            # incidentes seguintes
            max(duration_seconds, 0.0)
        )

    def record_inference_latency(self, model_id: str, duration: float) -> None:
        INFERENCE_LATENCY.labels(model_id=model_id).observe(duration)

    def record_pipeline_latency(self, sensor_id: str, duration: float) -> None:
        PIPELINE_LATENCY.labels(sensor_id=sensor_id).observe(duration)

    # --- métodos privados ---

    @staticmethod
    def _unregister_defaults() -> None:
        """
        Tira os collectors que o prometheus_client registra sozinho: métricas
        de GC, de plataforma e de processo poluem o Grafana e não dizem nada
        sobre o dispositivo.

        KeyError é engolido porque a operação não é idempotente e o registro
        é global: num processo com dois exportadores, o segundo start() acha
        tudo já removido.
        """
        for collector in (
            prometheus_client.GC_COLLECTOR,
            prometheus_client.PLATFORM_COLLECTOR,
            prometheus_client.PROCESS_COLLECTOR,
        ):
            with contextlib.suppress(KeyError):
                prometheus_client.REGISTRY.unregister(collector)

        # a métrica _created de cada counter dobra o número de séries sem
        # dizer nada que o próprio counter não diga. O ignore é da biblioteca:
        # a função não tem anotação e o mypy roda estrito aqui
        prometheus_client.disable_created_metrics()  # type: ignore[no-untyped-call]

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
