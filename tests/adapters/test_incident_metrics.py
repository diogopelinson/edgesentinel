"""
Métricas de incidente nos dois exportadores.

A divisão que estes testes fixam: o gauge de abertos é lido da loja a cada
scrape, e o contador e o histograma são acumulados no processo. Não é
simetria por gosto — um gauge de estado atual precisa estar certo depois de
um restart e depois de um ack feito pela CLI, e um contador precisa ser
monotônico, o que a loja não garante porque prune() apaga incidente
resolvido.
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
    Só open_incidents() importa aqui — é o único método que o collector usa.
    O resto levanta de propósito: se o collector começar a escrever na loja
    durante um scrape, o teste quebra em vez de passar.
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
    """Um scrape do collector, como {(rule, severity, state): valor}."""
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
    """Valor de uma amostra no registro global, 0.0 quando a série não existe."""
    from prometheus_client import REGISTRY
    valor = REGISTRY.get_sample_value(name, labels)
    return 0.0 if valor is None else valor


# --- o agrupamento ---

class TestCountOpen:
    """
    O gauge é uma contagem por rótulo, e os rótulos são três: regra,
    severidade e estado. O estado entra porque 'aberto e ninguém viu' é a
    pergunta que o operador faz, e sem ele a soma não sabe responder.
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


# --- o gauge, lido a cada scrape ---

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
        Série esparsa é a prática do Prometheus: sem incidente aberto não há
        combinação de rótulos para publicar. O painel soma com
        'or vector(0)' — publicar zero para toda regra que já disparou
        deixaria séries mortas para sempre.
        """
        assert scrape(OpenIncidentsCollector(FakeIncidents())) == {}

    def test_reads_the_store_on_every_scrape(self):
        """
        Um gauge de estado atual que guardasse o valor mentiria depois de um
        restart: o incidente continua aberto no banco e o processo começou
        com o contador em zero.
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
        Um scrape que levanta derruba o endpoint inteiro — todas as outras
        métricas vão embora junto. Banco travado é o caso comum num cartão SD.
        """
        amostras = scrape(OpenIncidentsCollector(FakeIncidents(failing=True)))

        assert amostras == {}

    def test_a_failing_store_is_logged(self, caplog):
        with caplog.at_level(logging.ERROR):
            scrape(OpenIncidentsCollector(FakeIncidents(failing=True)))

        assert "database is locked" in caplog.text


# --- o contador e o histograma, no processo ---

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
        O relógio do dispositivo anda para trás quando o NTP acerta. Duração
        negativa somada no histograma corrompe o P95 de todas as leituras
        seguintes, então ela entra como zero.
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
        Um incidente de edge dura de segundos (um pico de CPU) a dias (um
        disco cheio que ninguém viu). Buckets só até um minuto jogariam
        tudo o que importa no +Inf.
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
        Sem event_store habilitado não existe incidente. Registrar o
        collector publicaria um gauge que nunca sai de vazio.
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


# --- o mesmo no OTel ---

class TestOTelIncidentMetrics:
    """
    Os dois exportadores seguem suportados, então as três métricas têm de
    existir nos dois com o mesmo nome depois da conversão do reader.

    Os testes montam os instrumentos direto num meter de memória em vez de
    chamar start(): start() abre socket (backend prometheus) ou fala gRPC
    (backend otlp), e nenhum dos dois cabe num teste.
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
        if dados is None:      # nenhum instrumento produziu ponto nesta coleta
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
        No OTel o equivalente do collector é um gauge observável: o SDK
        chama a callback na hora de exportar, e é ali que a loja é lida.
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
        A callback roda dentro da coleta: se ela levantar, o SDK perde o
        ciclo inteiro e as outras métricas vão embora junto. O contador é
        alimentado aqui justamente para provar que o resto da coleta saiu.
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
        O reader do Prometheus troca ponto por underscore e acrescenta a
        unidade ao nome — é de onde vem o '_seconds' do histograma. Se um
        dos dois lados for renomeado sem o outro, o dashboard passa a
        funcionar em metade das instalações.
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
