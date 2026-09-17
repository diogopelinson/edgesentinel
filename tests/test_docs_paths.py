"""
Caminhos citados na documentação precisam existir no repositório.

Só entra o que é versionado: links relativos em markdown e arquivos de
dashboards/. Arquivos gerados em execução (models/*.onnx, data/events.db)
ficam de fora de propósito.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "README-BR.md", "USAGE-EN.md", "USAGE-PTBR.md", "CHANGELOG.md", "models/README.md"]

_LINK = re.compile(r"\]\(([^)\s]+)\)")
_DASHBOARD = re.compile(r"`(dashboards/[^`]+)`")

# a seção de 0.3.0 registra, de propósito, o caminho errado que existia na época
_HISTORICAL = {("CHANGELOG.md", "dashboards/edgesentinel.json")}


def relative_links(doc: str) -> list[str]:
    text = (ROOT / doc).read_text(encoding="utf-8")
    return [
        target.split("#")[0]
        for target in _LINK.findall(text)
        if not target.startswith(("http://", "https://", "#", "mailto:"))
    ]


def dashboard_paths(doc: str) -> list[str]:
    text = (ROOT / doc).read_text(encoding="utf-8")
    return [p for p in _DASHBOARD.findall(text) if (doc, p) not in _HISTORICAL]


@pytest.mark.parametrize("doc", DOCS)
def test_relative_links_point_to_existing_files(doc):
    base = (ROOT / doc).parent
    missing = [t for t in relative_links(doc) if t and not (base / t).exists()]

    assert missing == [], f"{doc} aponta para arquivos inexistentes: {missing}"


@pytest.mark.parametrize("doc", DOCS)
def test_dashboard_files_mentioned_exist(doc):
    missing = [p for p in dashboard_paths(doc) if not (ROOT / p).exists()]

    assert missing == [], f"{doc} cita dashboards inexistentes: {missing}"
