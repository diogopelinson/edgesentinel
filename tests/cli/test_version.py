"""
The version lives in a single place: cli.__version__. The pyproject.toml reads
it from there, and --version shows it. This file makes sure the three do not
drift apart.
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
    """Two declarations end up diverging — that is how 0.1.0 got duplicated."""
    source = (ROOT / "cli" / "main.py").read_text(encoding="utf-8")

    assert not re.search(r"^__version__\s*=", source, re.M)


def test_pyproject_has_no_static_version():
    import tomli

    project = tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert "version" not in project
    assert "version" in project.get("dynamic", [])


def test_pyproject_resolves_to_the_package_version():
    """Resolves the way setuptools does at build time — not just checking the text of the TOML."""
    read_configuration = pytest.importorskip("setuptools.config.pyprojecttoml").read_configuration
    from cli import __version__

    # the root for resolving attr= comes from the directory of the pyproject.toml itself
    config = read_configuration(ROOT / "pyproject.toml", expand=True)

    assert config["project"]["version"] == __version__


@pytest.mark.parametrize("readme", ["README.md", "README-BR.md"])
def test_readmes_state_the_current_version(readme):
    """The version written in the README must not fall behind on the next release."""
    from cli import __version__

    text = (ROOT / readme).read_text(encoding="utf-8")

    assert f"**{__version__}**" in text


def test_changelog_has_an_entry_for_the_current_version():
    """Bumping the version without release notes leaves the tag without an explanation."""
    from cli import __version__

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert re.search(rf"^## \[{re.escape(__version__)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M)


def test_the_module_can_be_run_with_dash_m():
    """
    The console script of the venv embeds the absolute path of where the venv
    was created and breaks when the project changes folder. 'python -m cli.main'
    is the documented way out for that case — and it only works with the
    __main__ block.
    """
    import subprocess

    from cli import __version__

    resultado = subprocess.run(
        [sys.executable, "-m", "cli.main", "--version"],
        cwd=ROOT, capture_output=True, text=True,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == f"edgesentinel {__version__}"
