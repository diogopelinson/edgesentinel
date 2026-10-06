"""
Paths cited in the documentation have to exist in the repository.

Only what is versioned counts: relative markdown links and files under
dashboards/. Files generated at runtime (models/*.onnx, data/events.db) are
left out on purpose.

The .md files are discovered, not listed: a new document enters the check just
by existing, which is the only way for the list not to fall behind.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# directories that are not the project's documentation
_IGNORADOS = {".venv", ".git", "node_modules", "__pycache__", ".pytest_cache", "build", "dist"}

# AGENTS.md beyond this stops being followed — the convention itself says so
AGENTS_MAX_LINHAS = 300

_LINK = re.compile(r"\]\(([^)\s]+)\)")
_DASHBOARD = re.compile(r"`(dashboards/[^`]+)`")

# the 0.3.0 section records, on purpose, the wrong path that existed at the time
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
    """If the rglob stops finding the .md files, the tests below pass without checking anything."""
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
    A page the index does not cite is a page nobody finds: Diataxis navigation
    is each directory's index, not the file listing.
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
