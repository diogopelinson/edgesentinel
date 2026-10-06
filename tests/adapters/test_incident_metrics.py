"""
Incident metrics in both exporters.

The division these tests pin down: the gauge of open incidents is read from the
store on every scrape, and the counter and the histogram are accumulated in the
process. It is not symmetry for its own sake — a current-state gauge has to be
right after a restart and after an ack done through the CLI, and a counter has
to be monotonic, which the store does not guarantee because prune() deletes
resolved incidents.
"""
import logging
import sqlite3

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from adapters.exporter.incidents import OpenIncidentsCollector, count_open
from adapters.exporter.metrics import INCIDENT_DURATION, INCIDENTS_TOTAL
from adapters.exporter.prometheus import PrometheusExporter
from core.incidents import Incident, IncidentState
from core.ports import IncidentMetricsPort, IncidentPort

GAUGE = "edgesentinel_incidents_open"


# --- helpers ---

def incident(
    rule: str = "hot",
    severity: str = "warning",
    state: IncidentState = IncidentState.TRIGGERED,
    incident_id: int = 1,
    opened_at: float = 1_000.0,
) -> Incident:
    return Incident(
        rule_name=rule,
        sensor_id="cpu_temp",
        severity=severity,
        state=state,
        opened_at=opened_at,
        incident_id=incident_id,
    )


class FakeIncidents(IncidentPort):
    """
    Only open_incidents() matters here — it is the only method the collector
    uses. The rest raises on purpose: if the collector starts writing to the
    store during a scrape, the test breaks instead of passing.
    """

    def __init__(self, *incidents: Incident, failing: bool = False) -> None:
        self.incidents = list(incidents)
        self.failing = failing
        self.reads = 0

    def open_incidents(self) -> list[Incident]:
        self.reads += 1
        if self.failing:
            raise sqlite3.OperationalError("database is locked")
        return list(self.incidents)

    def open_incident(self, incident: Incident) -> Incident:
        raise NotImplementedError

    def acknowledge_incident(self, incident_id: int, at: float) -> None:
        raise NotImplementedError

    def resolve_incident(self, incident_id: int, at: float) -> None:
        raise NotImplementedError


def scrape(collector: OpenIncidentsCollector) -> dict[tuple[str, ...], float]:
    """One scrape of the collector, as {(rule, severity, state): value}."""
    registry = CollectorRegistry()
    registry.register(collector)
    amostras = {}
    for familia in registry.collect():
        for amostra in familia.samples:
            chave = (
                amostra.labels["rule"],
                amostra.labels["severity"],
                amostra.labels["state"],
            )
            amostras[chave] = amostra.value
    return amostras


def sample(name: str, **labels: str) -> float:
    """The value of a sample in the global registry, 0.0 when the series does not exist."""
    from prometheus_client import REGISTRY
    valor = REGISTRY.get_sample_value(name, labels)
    return 0.0 if valor is None else valor


# --- the grouping ---

class TestCountOpen:
    """
    The gauge is a count per label, and the labels are three: rule, severity
    and state. The state is in there because 'open and nobody has seen it' is
    the question the operator asks, and without it the sum cannot answer.
    """

    def test_groups_by_rule_severity_and_state(self):
        contagem = count_open([
            incident(rule="hot", severity="warning", incident_id=1),
            incident(rule="full_disk", severity="critical", incident_id=2),
        ])

        assert contagem == {
            ("hot", "warning", "triggered"): 1,
            ("full_disk", "critical", "triggered"): 1,
        }

    def test_the_state_separates_acknowledged_from_triggered(self):
        contagem = count_open([
            incident(rule="hot", incident_id=1),
            incident(rule="cold", state=IncidentState.ACKNOWLEDGED, incident_id=2),
        ])

        assert contagem[("hot", "warning", "triggered")] == 1
        assert contagem[("cold", "warning", "acknowledged")] == 1

    def test_nothing_open_is_an_empty_mapping(self):
        assert count_open([]) == {}


# --- the gauge, read on every scrape ---

class TestOpenIncidentsCollector:

    def test_exposes_one_series_per_group(self):
        loja = FakeIncidents(
            incident(rule="hot", severity="warning", incident_id=1),
            incident(rule="full_disk", severity="critical", incident_id=2),
        )

        amostras = scrape(OpenIncidentsCollector(loja))

        assert amostras == {
            ("hot", "warning", "triggered"): 1.0,
            ("full_disk", "critical", "triggered"): 1.0,
        }

    def test_the_series_is_named_after_the_legacy_metric(self):
        loja = FakeIncidents(incident())
        registry = CollectorRegistry()
        registry.register(OpenIncidentsCollector(loja))

        texto = generate_latest(registry).decode()

        assert f"{GAUGE}{{" in texto
        assert "# TYPE edgesentinel_incidents_open gauge" in texto

    def test_nothing_open_exposes_no_series(self):
        """
        Sparse series is the Prometheus practice: with no open incident there
        is no label combination to publish. The dashboard sums with
        'or vector(0)' — publishing zero for every rule that has ever fired
        would leave dead series behind forever.
        """
        assert scrape(OpenIncidentsCollector(FakeIncidents())) == {}

    def test_reads_the_store_on_every_scrape(self):
        """
        A current-state gauge that cached the value would lie after a restart:
        the incident is still open in the database and the process started with
        the counter at zero.
        """
        loja = FakeIncidents(incident())
        collector = OpenIncidentsCollector(loja)

        scrape(collector)
        scrape(collector)

        assert loja.reads == 2

    def test_an_acknowledgement_between_scrapes_moves_the_series(self):
        loja = FakeIncidents(incident(rule="hot", incident_id=1))
        collector = OpenIncidentsCollector(loja)

        assert scrape(collector) == {("hot", "warning", "triggered"): 1.0}

        loja.incidents = [incident(
            rule="hot", incident_id=1, state=IncidentState.ACKNOWLEDGED,
        )]

        assert scrape(collector) == {("hot", "warning", "acknowledged"): 1.0}

    def test_a_failing_store_does_not_break_the_scrape(self):
        """
        A scrape that raises brings down the whole endpoint — all the other
        metrics go with it. A locked database is the common case on an SD card.
        """
        amostras = scrape(OpenIncidentsCollector(FakeIncidents(failing=True)))

        assert amostras == {}

    def test_a_failing_store_is_logged(self, caplog):
        with caplog.at_level(logging.ERROR):
            scrape(OpenIncidentsCollector(FakeIncidents(failing=True)))

        assert "database is locked" in caplog.text


# --- the counter and the histogram, in the process ---

class TestPrometheusIncidentMetrics:

    @pytest.fixture
    def exporter(self) -> PrometheusExporter:
        return PrometheusExporter(port=0)

    def test_the_exporter_honours_the_incident_metrics_port(self, exporter):
        assert isinstance(exporter, IncidentMetricsPort)

    def test_opening_counts_a_transition(self, exporter):
        antes = sample(
            "edgesentinel_incidents_total",
            rule="conta_abertura", severity="warning", transition="opened",
        )

        exporter.record_incident_opened(incident(rule="conta_abertura"))

        depois = sample(
            "edgesentinel_incidents_total",
            rule="conta_abertura", severity="warning", transition="opened",
        )
        assert depois - antes == 1.0

    def test_resolving_counts_its_own_transition(self, exporter):
        antes = sample(
            "edgesentinel_incidents_total",
            rule="conta_fechamento", severity="critical", transition="resolved",
        )

        exporter.record_incident_resolved(
            incident(rule="conta_fechamento", severity="critical"),
            duration_seconds=12.0,
        )

        depois = sample(
            "edgesentinel_incidents_total",
            rule="conta_fechamento", severity="critical", transition="resolved",
        )
        assert depois - antes == 1.0

    def test_resolving_observes_the_duration(self, exporter):
        antes_soma = sample(
            "edgesentinel_incident_duration_seconds_sum", severity="warning",
        )
        antes_conta = sample(
            "edgesentinel_incident_duration_seconds_count", severity="warning",
        )

        exporter.record_incident_resolved(incident(), duration_seconds=90.0)

        assert sample(
            "edgesentinel_incident_duration_seconds_sum", severity="warning",
        ) - antes_soma == 90.0
        assert sample(
            "edgesentinel_incident_duration_seconds_count", severity="warning",
        ) - antes_conta == 1.0

    def test_a_negative_duration_is_clamped(self, exporter):
        """
        The device's clock walks backwards when NTP corrects it. A negative
        duration summed into the histogram corrupts the P95 of every subsequent
        reading, so it goes in as zero.
        """
        antes = sample(
            "edgesentinel_incident_duration_seconds_sum", severity="info",
        )

        exporter.record_incident_resolved(
            incident(severity="info"), duration_seconds=-30.0,
        )

        depois = sample(
            "edgesentinel_incident_duration_seconds_sum", severity="info",
        )
        assert depois == antes

    def test_the_instruments_carry_the_documented_labels(self):
        assert INCIDENTS_TOTAL._labelnames == ("rule", "severity", "transition")
        assert INCIDENT_DURATION._labelnames == ("severity",)

    def test_the_duration_buckets_span_seconds_to_a_day(self):
        """
        An edge incident lasts from seconds (a CPU spike) to days (a full disk
        nobody saw). Buckets only up to one minute would throw everything that
        matters into the +Inf.
        """
        assert INCIDENT_DURATION._upper_bounds[0] <= 5.0
        assert 86_400.0 in INCIDENT_DURATION._upper_bounds

    def test_the_collector_is_registered_when_the_store_is_there(self, monkeypatch):
        registrados = []
        monkeypatch.setattr(
            "adapters.exporter.prometheus.prometheus_client.REGISTRY.register",
            registrados.append,
        )
        monkeypatch.setattr(
            "adapters.exporter.prometheus.prometheus_client.start_http_server",
            lambda port: None,
        )
        monkeypatch.setattr(
            "adapters.exporter.prometheus.PrometheusExporter._unregister_defaults",
            lambda self: None,
        )

        PrometheusExporter(port=0, incidents=FakeIncidents()).start()

        assert any(isinstance(c, OpenIncidentsCollector) for c in registrados)

    def test_without_a_store_no_collector_is_registered(self, monkeypatch):
        """
        With no event_store enabled there is no such thing as an incident.
        Registering the collector would publish a gauge that never leaves empty.
        """
        registrados = []
        monkeypatch.setattr(
            "adapters.exporter.prometheus.prometheus_client.REGISTRY.register",
            registrados.append,
        )
        monkeypatch.setattr(
            "adapters.exporter.prometheus.prometheus_client.start_http_server",
            lambda port: None,
        )
        monkeypatch.setattr(
            "adapters.exporter.prometheus.PrometheusExporter._unregister_defaults",
            lambda self: None,
        )

        PrometheusExporter(port=0).start()

        assert not any(isinstance(c, OpenIncidentsCollector) for c in registrados)


# --- the same in OTel ---

class TestOTelIncidentMetrics:
    """
    Both exporters remain supported, so the three metrics have to exist in both
    under the same name after the reader's conversion.

    The tests build the instruments straight onto an in-memory meter instead of
    calling start(): start() opens a socket (prometheus backend) or speaks gRPC
    (otlp backend), and neither of the two fits inside a test.
    """

    @pytest.fixture
    def sdk(self):
        pytest.importorskip("opentelemetry.sdk.metrics")
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        return MeterProvider, InMemoryMetricReader

    def build(self, sdk, loja):
        from adapters.exporter.otel import OTelExporter
        MeterProvider, InMemoryMetricReader = sdk

        reader = InMemoryMetricReader()
        meter = MeterProvider(metric_readers=[reader]).get_meter("test")

        exporter = OTelExporter(incidents=loja)
        exporter._setup_instruments(meter)
        exporter._started = True
        return exporter, reader

    def collected(self, reader) -> dict[str, object]:
        dados = reader.get_metrics_data()
        if dados is None:      # no instrument produced a point in this collection
            return {}
        metricas = {}
        for resource in dados.resource_metrics:
            for scope in resource.scope_metrics:
                for metrica in scope.metrics:
                    metricas[metrica.name] = metrica
        return metricas

    def test_the_three_incident_metrics_are_exported(self, sdk):
        exporter, reader = self.build(sdk, FakeIncidents(incident()))

        exporter.record_incident_opened(incident())
        exporter.record_incident_resolved(incident(), duration_seconds=5.0)

        nomes = set(self.collected(reader))
        assert "edgesentinel.incidents.open" in nomes
        assert "edgesentinel.incidents.total" in nomes
        assert "edgesentinel.incident.duration" in nomes

    def test_the_observable_gauge_reads_the_store_at_collection(self, sdk):
        """
        In OTel the collector's equivalent is an observable gauge: the SDK
        calls the callback at export time, and that is where the store is read.
        """
        loja = FakeIncidents(
            incident(rule="hot", severity="warning", incident_id=1),
            incident(rule="full_disk", severity="critical", incident_id=2),
        )
        _, reader = self.build(sdk, loja)

        metrica = self.collected(reader)["edgesentinel.incidents.open"]
        pontos = {
            (p.attributes["rule"], p.attributes["severity"], p.attributes["state"]): p.value
            for p in metrica.data.data_points
        }

        assert loja.reads == 1
        assert pontos == {
            ("hot", "warning", "triggered"): 1,
            ("full_disk", "critical", "triggered"): 1,
        }

    def test_a_failing_store_does_not_break_the_collection(self, sdk):
        """
        The callback runs inside the collection: if it raises, the SDK loses
        the whole cycle and the other metrics go with it. The counter is fed
        here precisely to prove that the rest of the collection came out.
        """
        exporter, reader = self.build(sdk, FakeIncidents(failing=True))
        exporter.record_incident_opened(incident())

        coletado = self.collected(reader)

        assert "edgesentinel.incidents.total" in coletado
        assert "edgesentinel.incidents.open" not in coletado

    def test_without_a_store_the_gauge_is_not_created(self, sdk):
        _, reader = self.build(sdk, None)

        assert "edgesentinel.incidents.open" not in self.collected(reader)

    def test_the_counter_carries_the_same_attributes_as_the_legacy_labels(self, sdk):
        exporter, reader = self.build(sdk, FakeIncidents())

        exporter.record_incident_opened(incident(rule="hot"))

        (ponto,) = self.collected(reader)["edgesentinel.incidents.total"].data.data_points
        assert dict(ponto.attributes) == {
            "rule": "hot", "severity": "warning", "transition": "opened",
        }

    def test_both_exporters_publish_the_same_three_names(self, sdk):
        """
        The Prometheus reader swaps dots for underscores and appends the unit
        to the name — that is where the histogram's '_seconds' comes from. If
        one of the two sides is renamed without the other, the dashboard goes
        from working everywhere to working in half of the installations.
        """
        exporter, reader = self.build(sdk, FakeIncidents(incident()))
        exporter.record_incident_opened(incident())
        exporter.record_incident_resolved(incident(), duration_seconds=1.0)

        convertidos = set()
        for nome, metrica in self.collected(reader).items():
            sufixo = "_seconds" if metrica.unit == "s" else ""
            convertidos.add(nome.replace(".", "_") + sufixo)

        assert {
            "edgesentinel_incidents_open",
            "edgesentinel_incidents_total",
            "edgesentinel_incident_duration_seconds",
        } <= convertidos
