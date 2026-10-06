"""
The Grafana dashboard against the metrics the agent actually publishes.

A panel citing a metric that does not exist breaks nothing: it just goes empty,
and empty is indistinguishable from 'nothing happened'. A dashboard versioned
alongside the code can be checked against it, and that is what this file does.
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

# the AI Service has its own registry, in another process and another container
PREFIXOS_EXTERNOS = ("ai_service_",)

# metric names cited in a PromQL expression
_METRICA = re.compile(r"\b((?:edgesentinel|ai_service)_[a-z0-9_]+)\b")


def nomes_publicados() -> set[str]:
    """
    Every series the exporters can publish, derived from the instruments
    themselves instead of written by hand — a hand-written list ages silently.
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
    """(panel title, expression) for each target in the dashboard."""
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
        Grafana groups by position, not by nesting: a panel above its own row
        shows up in the previous row.
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
        The case this catches: renaming a metric in the exporter and leaving the
        panel pointing at the old name. Nothing fails, the panel just goes empty.
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
        The gauge is sparse: with no open incident there is no series, and a stat
        with no series shows 'No data' instead of zero. 'or vector(0)' is what
        makes the panel say 'none' when it is none.
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
