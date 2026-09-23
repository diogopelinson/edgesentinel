"""
Caminhos citados na documentação precisam existir no repositório.

Só entra o que é versionado: links relativos em markdown e arquivos de
dashboards/. Arquivos gerados em execução (models/*.onnx, data/events.db)
ficam de fora de propósito.

Os .md são descobertos, não listados: documento novo entra na verificação
por existir, que é o único jeito de a lista não ficar para trás.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# diretórios que não são documentação do projeto
_IGNORADOS = {".venv", ".git", "node_modules", "__pycache__", ".pytest_cache", "build", "dist"}

# AGENTS.md acima disso perde aderência — a própria convenção diz isso
AGENTS_MAX_LINHAS = 300

_LINK = re.compile(r"\]\(([^)\s]+)\)")
_DASHBOARD = re.compile(r"`(dashboards/[^`]+)`")

# a seção de 0.3.0 registra, de propósito, o caminho errado que existia na época
_HISTORICAL = {("CHANGELOG.md", "dashboards/edgesentinel.json")}


def markdown_files() -> list[str]:
    return sorted(
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("*.md")
        if not _IGNORADOS & set(p.relative_to(ROOT).parts)
    )


DOCS = markdown_files()


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


def test_the_documentation_was_actually_found():
    """Se o rglob parar de achar os .md, os testes abaixo passam sem verificar nada."""
    assert "README.md" in DOCS
    assert "docs/README.md" in DOCS
    assert len(DOCS) > 20


def test_relative_links_point_to_existing_files():
    quebrados = {
        doc: [alvo for alvo in relative_links(doc)
              if alvo and not ((ROOT / doc).parent / alvo).exists()]
        for doc in DOCS
        if any(alvo and not ((ROOT / doc).parent / alvo).exists()
               for alvo in relative_links(doc))
    }

    assert quebrados == {}, f"links para arquivos inexistentes: {quebrados}"


def test_dashboard_files_mentioned_exist():
    ausentes = {
        doc: [caminho for caminho in dashboard_paths(doc) if not (ROOT / caminho).exists()]
        for doc in DOCS
        if any(not (ROOT / caminho).exists() for caminho in dashboard_paths(doc))
    }

    assert ausentes == {}, f"dashboards citados que não existem: {ausentes}"


@pytest.mark.parametrize("secao", ["tutorials", "how-to", "reference", "explanation", "adr"])
def test_every_page_is_listed_in_its_index(secao):
    """
    Página que o índice não cita é página que ninguém encontra: a navegação
    do Diátaxis é o índice de cada diretório, não a listagem de arquivos.
    """
    diretorio = ROOT / "docs" / secao
    indice = (diretorio / "README.md").read_text(encoding="utf-8")
    citados = set(_LINK.findall(indice))

    orfas = [
        p.name for p in sorted(diretorio.glob("*.md"))
        if p.name != "README.md" and p.name not in citados
    ]

    assert orfas == [], f"docs/{secao}/README.md não cita: {orfas}"


def test_agents_md_stays_short_enough_to_be_followed():
    linhas = (ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()

    assert len(linhas) <= AGENTS_MAX_LINHAS, (
        f"AGENTS.md tem {len(linhas)} linhas; acima de {AGENTS_MAX_LINHAS} "
        f"as instruções do fim deixam de ser seguidas"
    )
