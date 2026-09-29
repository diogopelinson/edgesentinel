"""
O dashboard do Grafana contra as métricas que o agente realmente publica.

Um painel que cita uma métrica inexistente não quebra nada: ele só fica vazio,
e vazio é indistinguível de 'nada aconteceu'. Um dashboard versionado junto do
código pode ser verificado contra ele, e é o que este arquivo faz.
"""
import json
import re
from itertools import pairwise
from pathlib import Path

import pytest
from prometheus_client import Counter, Gauge, Histogram

from adapters.exporter import metrics as instrumentos
from adapters.exporter.incidents import NAME as GAUGE_ABERTOS

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboards"
ARQUIVO   = DASHBOARD / "edgesentinel_dashboard_v2.json"

# o AI Service tem o seu próprio registro, noutro processo e noutro container
PREFIXOS_EXTERNOS = ("ai_service_",)

# nomes de métrica citados numa expressão PromQL
_METRICA = re.compile(r"\b((?:edgesentinel|ai_service)_[a-z0-9_]+)\b")


def nomes_publicados() -> set[str]:
    """
    Todas as séries que os exportadores podem publicar, derivadas dos próprios
    instrumentos em vez de escritas à mão — uma lista à mão envelhece calada.
    """
    nomes = {GAUGE_ABERTOS}

    for objeto in vars(instrumentos).values():
        if isinstance(objeto, Counter):
            nomes.update({f"{objeto._name}_total", f"{objeto._name}_created"})
        elif isinstance(objeto, Gauge):
            nomes.add(objeto._name)
        elif isinstance(objeto, Histogram):
            nomes.update({
                f"{objeto._name}_bucket",
                f"{objeto._name}_sum",
                f"{objeto._name}_count",
            })

    return nomes


@pytest.fixture(scope="module")
def dashboard() -> dict:
    return json.loads(ARQUIVO.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def expressoes(dashboard) -> list[tuple[str, str]]:
    """(título do painel, expressão) para cada target do dashboard."""
    pares = []
    for painel in dashboard["panels"]:
        for target in painel.get("targets", []):
            if "expr" in target:
                pares.append((painel.get("title", "?"), target["expr"]))
    return pares


class TestDashboardStructure:

    def test_it_is_valid_json(self, dashboard):
        assert dashboard["title"] == "edgesentinel"

    def test_every_panel_has_a_unique_id(self, dashboard):
        ids = [p["id"] for p in dashboard["panels"]]

        assert len(ids) == len(set(ids))

    def test_every_non_row_panel_has_a_target(self, dashboard):
        sem_alvo = [
            p.get("title")
            for p in dashboard["panels"]
            if p["type"] != "row" and not p.get("targets")
        ]

        assert sem_alvo == []

    def test_rows_come_before_the_panels_they_hold(self, dashboard):
        """
        O Grafana agrupa por posição, não por aninhamento: um painel acima da
        sua própria linha aparece na linha anterior.
        """
        linhas = [p for p in dashboard["panels"] if p["type"] == "row"]

        for anterior, seguinte in pairwise(linhas):
            entre = [
                p for p in dashboard["panels"]
                if p["type"] != "row"
                and anterior["gridPos"]["y"] < p["gridPos"]["y"] < seguinte["gridPos"]["y"]
            ]
            assert entre, f"linha '{anterior['title']}' ficou sem painel"


class TestDashboardMatchesTheAgent:

    def test_every_metric_cited_exists(self, expressoes):
        """
        O caso que isto pega: renomear uma métrica no exportador e deixar o
        painel apontando para a antiga. Nada falha, o painel só fica vazio.
        """
        publicados = nomes_publicados()
        orfas = set()

        for titulo, expr in expressoes:
            for nome in _METRICA.findall(expr):
                if nome.startswith(PREFIXOS_EXTERNOS):
                    continue
                if nome not in publicados:
                    orfas.add(f"{nome} (painel '{titulo}')")

        assert orfas == set()

    def test_the_incident_metrics_reached_the_dashboard(self, expressoes):
        todas = " ".join(expr for _, expr in expressoes)

        assert "edgesentinel_incidents_open" in todas
        assert "edgesentinel_incidents_total" in todas
        assert "edgesentinel_incident_duration_seconds_bucket" in todas

    def test_the_open_gauge_is_summed_with_a_fallback(self, expressoes):
        """
        O gauge é esparso: sem incidente aberto não há série, e um stat sem
        série mostra 'No data' em vez de zero. 'or vector(0)' é o que faz o
        painel dizer 'nenhum' quando é nenhum.
        """
        stats = [
            expr for titulo, expr in expressoes
            if expr.startswith("sum(edgesentinel_incidents_open")
        ]

        assert stats, "nenhum painel soma o gauge de abertos"
        for expr in stats:
            assert "or vector(0)" in expr

    def test_the_incident_row_exists(self, dashboard):
        linhas = [p["title"] for p in dashboard["panels"] if p["type"] == "row"]

        assert "Incidentes" in linhas
