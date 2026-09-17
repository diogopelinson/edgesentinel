"""
A versão vive num lugar só: cli.__version__. O pyproject.toml a lê de lá,
e --version a mostra. Este arquivo garante que os três não se separem.
"""
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_version_is_semantic():
    from cli import __version__

    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_version_flag_prints_the_package_version(capsys):
    from cli import __version__
    from cli.main import _parse_args

    with patch.object(sys, "argv", ["edgesentinel", "--version"]), \
         pytest.raises(SystemExit) as exc:
        _parse_args()

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"edgesentinel {__version__}"


def test_cli_main_does_not_declare_its_own_version():
    """Duas declarações acabam divergindo — foi assim que 0.1.0 ficou duplicado."""
    source = (ROOT / "cli" / "main.py").read_text(encoding="utf-8")

    assert not re.search(r"^__version__\s*=", source, re.M)


def test_pyproject_has_no_static_version():
    import tomli

    project = tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert "version" not in project
    assert "version" in project.get("dynamic", [])


def test_pyproject_resolves_to_the_package_version():
    """Resolve como o setuptools faz no build — não só confere o texto do TOML."""
    read_configuration = pytest.importorskip("setuptools.config.pyprojecttoml").read_configuration
    from cli import __version__

    # a raiz para resolver attr= vem do diretório do próprio pyproject.toml
    config = read_configuration(ROOT / "pyproject.toml", expand=True)

    assert config["project"]["version"] == __version__


@pytest.mark.parametrize("readme", ["README.md", "README-BR.md"])
def test_readmes_state_the_current_version(readme):
    """A versão escrita no README não pode ficar para trás na próxima release."""
    from cli import __version__

    text = (ROOT / readme).read_text(encoding="utf-8")

    assert f"**{__version__}**" in text


def test_changelog_has_an_entry_for_the_current_version():
    """Subir a versão sem notas de release deixa a tag sem explicação."""
    from cli import __version__

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert re.search(rf"^## \[{re.escape(__version__)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M)
