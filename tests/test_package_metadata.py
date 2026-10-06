"""
The package description is what PyPI and pip show, next to the README.md
that pyproject.toml publishes. The two have to tell the same story, in the
same language.
"""
import re
from pathlib import Path

import tomli

ROOT = Path(__file__).resolve().parents[1]


def project_table() -> dict:
    return tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def readme_tagline() -> str:
    """The README's first quote line — the project's one-sentence summary."""
    readme = (ROOT / project_table()["readme"]).read_text(encoding="utf-8")
    return re.search(r"^> (.+)$", readme, re.M).group(1)


def test_description_opens_the_readme_tagline():
    description = project_table()["description"]

    assert readme_tagline().startswith(description), (description, readme_tagline())


def test_description_is_a_single_line_without_trailing_period():
    description = project_table()["description"]

    assert "\n" not in description
    assert not description.endswith(".")
