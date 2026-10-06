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
    Exports edgesentinel metrics to Prometheus.
    Brings up an HTTP server on the configured port that answers
    the Prometheus scrape at /metrics.

    With an incident store in hand, it also publishes how many are open right
    now — a number read from there on every scrape, not accumulated here.
    """

    def __init__(self, port: int = 8000, incidents: IncidentPort | None = None) -> None:
        self._port = port
        self._incidents = incidents
        self._started = False

    def start(self) -> None:
        """
        Starts the HTTP server in the background.
        Called once by MonitorLoop at startup.
        """
        if self._started:
            return

        self._unregister_defaults()

        # the open gauge is read from the store at scrape time. Without an
        # event_store there is no incident, and registering here would publish
        # a gauge that never stops being empty
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
        Updates the metrics with the data from one reading.
        Called by the Pipeline after each complete cycle.
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
            # the device clock walks backwards when NTP corrects it. A
            # negative duration added here corrupts the quantile of every
            # later incident
            max(duration_seconds, 0.0)
        )

    def record_inference_latency(self, model_id: str, duration: float) -> None:
        INFERENCE_LATENCY.labels(model_id=model_id).observe(duration)

    def record_pipeline_latency(self, sensor_id: str, duration: float) -> None:
        PIPELINE_LATENCY.labels(sensor_id=sensor_id).observe(duration)

    # --- private methods ---

    @staticmethod
    def _unregister_defaults() -> None:
        """
        Removes the collectors prometheus_client registers on its own: GC,
        platform and process metrics pollute Grafana and say nothing about the
        device.

        KeyError is swallowed because the operation is not idempotent and the
        registry is global: in a process with two exporters, the second start()
        finds everything already removed.
        """
        for collector in (
            prometheus_client.GC_COLLECTOR,
            prometheus_client.PLATFORM_COLLECTOR,
            prometheus_client.PROCESS_COLLECTOR,
        ):
            with contextlib.suppress(KeyError):
                prometheus_client.REGISTRY.unregister(collector)

        # the _created metric of each counter doubles the number of series
        # without saying anything the counter itself does not say. The ignore
        # is the library's fault: the function has no annotation and mypy runs
        # strict here
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
