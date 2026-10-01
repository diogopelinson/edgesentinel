"""
Comments and docstrings are in English, and this is what enforces it.

The documentation was already in English while the code was not, which closed
half the project to the reader a public repository exists for. The comments in
this codebase explain which decision was taken and what was rejected rather
than what the next line does, so they are the part worth reading — and the part
that was shut.

Scope, deliberately: comments and docstrings only.

Runtime strings — error messages, log lines, CLI output — stay in Portuguese.
Changing those would break the tests that assert that text and invalidate every
captured output under `docs/`, which is itself verified. Identifiers stay too:
renaming locals is a different change with a different risk. Both boundaries are
tests below, not notes, so the scope cannot drift by accident.
"""
import ast
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# directories that are not ours to rewrite
SKIP = {".venv", ".git", "__pycache__", "node_modules", "build", "dist", ".pytest_cache"}

# Accented Latin letters. English prose does not need them, and a Portuguese
# sentence of any length has one.
ACCENTED = set("áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ")

# Non-ASCII that English comments legitimately use: units, typography, and the
# arrows this codebase draws its pipelines with. Banning every non-ASCII
# character would have forced "72.5 degrees C" and ASCII arrows.
#
# Spelled as code points rather than literals so that ruff's
# ambiguous-character rule stays on for the rest of the repository, where it is
# wanted: an en dash where a hyphen was meant is worth catching everywhere else.
_ALLOWED_CODEPOINTS = (
    (0x00B0, "degree sign"),
    (0x00B5, "micro sign"),
    (0x00B1, "plus-minus"),
    (0x00B7, "middle dot"),
    (0x00D7, "multiplication sign"),
    (0x00F7, "division sign"),
    (0x00A0, "no-break space"),
    (0x2011, "non-breaking hyphen"),
    (0x2013, "en dash"),
    (0x2014, "em dash"),
    (0x2026, "horizontal ellipsis"),
    (0x2190, "leftwards arrow"),
    (0x2191, "upwards arrow"),
    (0x2192, "rightwards arrow"),
    (0x2193, "downwards arrow"),
    (0x2248, "almost equal to"),
    (0x2264, "less-than or equal to"),
    (0x2265, "greater-than or equal to"),
    (0x03A9, "greek capital omega"),
    (0x201C, "left double quotation mark"),
    (0x201D, "right double quotation mark"),
    (0x2018, "left single quotation mark"),
    (0x2019, "right single quotation mark"),
)

ALLOWED_SYMBOLS = {chr(ponto) for ponto, _ in _ALLOWED_CODEPOINTS}

# Portuguese words carrying no accent, which the letter check alone misses.
# Matched as whole words, and only words that are not also English — "sensor",
# "thread" and "normal" are deliberately absent.
PORTUGUESE_WORDS = frozenset({
    "nao", "que", "para", "com", "sem", "mas", "uma", "dos", "das", "pelo",
    "pela", "pelos", "pelas", "isso", "isto", "aqui", "ali", "ja", "ser",
    "ter", "faz", "fez", "cada", "quem", "onde", "quando", "mesmo", "mesma",
    "entre", "sobre", "depois", "antes", "ainda", "entao", "tambem", "vez",
    "vezes", "tudo", "quanto", "quantos", "sempre", "nunca", "porque",
    "porem", "contudo", "embora", "enquanto", "assim", "leitura", "escrita",
    "regra", "regras", "disparo", "disparos", "incidente", "incidentes",
    "arquivo", "arquivos", "banco", "estado", "falha", "falhas", "erro",
    "erros", "chave", "chaves", "nome", "nomes", "valor", "valores", "tempo",
    "janela", "limiar", "memoria", "processo", "processos", "fila", "lote",
    "caminho", "caminhos", "campo", "campos", "linha", "linhas", "teste",
    "testes", "painel", "coluna", "colunas", "tabela", "medicao", "contagem",
    "soma", "numero", "numeros", "segundos", "minutos", "horas", "dias",
})


def python_files() -> list[Path]:
    return sorted(
        p for p in ROOT.rglob("*.py")
        if not any(part in SKIP for part in p.relative_to(ROOT).parts)
    )


def _words(text: str) -> set[str]:
    cleaned = "".join(ch if ch.isalpha() or ch.isspace() else " " for ch in text)
    return {w.lower() for w in cleaned.split()}


def portuguese_reason(text: str) -> str | None:
    """
    Why the text looks Portuguese, or None.

    Two signals rather than one. The accented letter catches nearly everything
    and costs nothing; the word list catches the short ASCII-only comment the
    letter check would wave through.
    """
    accented = {c for c in text if c in ACCENTED}
    if accented:
        return f"accented letter {''.join(sorted(accented))!r}"

    found = _words(text) & PORTUGUESE_WORDS
    if found:
        return f"portuguese word {sorted(found)}"

    return None


def comments_in(path: Path) -> list[tuple[int, str]]:
    """Every comment in the file, as (line, text)."""
    with tokenize.open(str(path)) as f:
        return [
            (tok.start[0], tok.string)
            for tok in tokenize.generate_tokens(f.readline)
            if tok.type == tokenize.COMMENT
        ]


def docstrings_in(path: Path) -> list[tuple[int, str]]:
    """
    Every docstring in the file, as (line, text).

    Walks the AST instead of matching quoted text, so a Portuguese *string
    literal* is never mistaken for a docstring. That distinction is the scope of
    this check, and it has its own tests below.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            doc = ast.get_docstring(node)
            if doc:
                found.append((getattr(node, "lineno", 1), doc))
    return found


def offences(path: Path) -> list[str]:
    """Portuguese comments and docstrings in one file, as readable lines."""
    try:
        label = path.relative_to(ROOT).as_posix()
    except ValueError:
        label = path.name           # a sample written outside the repo, by a test

    found = []

    for line, text in comments_in(path):
        reason = portuguese_reason(text)
        if reason:
            found.append(f"{label}:{line} comment — {reason}: {text.strip()[:70]}")

    for line, text in docstrings_in(path):
        reason = portuguese_reason(text)
        if reason:
            first = text.strip().splitlines()[0][:70]
            found.append(f"{label}:{line} docstring — {reason}: {first}")

    return found


class TestEveryCommentAndDocstringIsEnglish:

    def test_the_whole_repository_passes(self):
        found = []
        for path in python_files():
            found.extend(offences(path))

        assert found == [], (
            f"{len(found)} Portuguese comment(s)/docstring(s):\n"
            + "\n".join(found[:40])
        )

    def test_there_is_something_to_check(self):
        """
        A check that scans nothing passes forever. If the walk breaks, this
        fails instead of the suite going quietly green.
        """
        assert len(python_files()) > 50


class TestTheGuardBites:
    """
    The check has to find planted Portuguese in both places, and has to leave
    runtime strings and identifiers alone — that boundary is this feature's
    scope decision, and it belongs in a test rather than in a note.
    """

    def write(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / "sample.py"
        path.write_text(body, encoding="utf-8")
        return path

    def test_it_finds_an_accented_comment(self, tmp_path):
        path = self.write(tmp_path, "x = 1  # a decisão está aqui\n")

        assert offences(path) != []

    def test_it_finds_an_unaccented_portuguese_comment(self, tmp_path):
        """The letter check alone would wave this one through."""
        path = self.write(tmp_path, "x = 1  # isso vale para cada disparo\n")

        assert offences(path) != []

    def test_it_finds_a_portuguese_module_docstring(self, tmp_path):
        path = self.write(tmp_path, '"""Lê a medição do sensor."""\n')

        assert offences(path) != []

    def test_it_finds_a_portuguese_function_docstring(self, tmp_path):
        path = self.write(
            tmp_path,
            'def f():\n    """Devolve a leitura já convertida."""\n    return 1\n',
        )

        assert offences(path) != []

    def test_it_finds_a_portuguese_class_docstring(self, tmp_path):
        path = self.write(
            tmp_path,
            'class C:\n    """Guarda o estado entre avaliações."""\n',
        )

        assert offences(path) != []

    def test_it_leaves_a_runtime_string_alone(self, tmp_path):
        """
        This feature's scope, as a test. Error messages and log lines stay in
        Portuguese, so Portuguese inside a string literal has to pass — and it
        is why docstrings are found through the AST rather than by matching
        quoted text.
        """
        path = self.write(
            tmp_path,
            'def f():\n'
            '    raise ValueError("Sensor não disponível nesse hardware.")\n',
        )

        assert offences(path) == []

    def test_it_leaves_a_multiline_runtime_string_alone(self, tmp_path):
        """
        A triple-quoted string that is not in docstring position is data, not a
        docstring. ast.get_docstring knows the difference; a text search would
        not.
        """
        path = self.write(
            tmp_path,
            'def f():\n'
            '    message = """\n'
            '    Nenhuma fonte de temperatura encontrada.\n'
            '    """\n'
            '    return message\n',
        )

        assert offences(path) == []

    def test_it_leaves_portuguese_identifiers_alone(self, tmp_path):
        """
        The other boundary. Locals in this codebase are named in Portuguese and
        renaming them is a different change with a different risk, so the check
        must not creep into it.
        """
        path = self.write(
            tmp_path,
            "def contagem_de_disparos(leitura):\n"
            "    marcadores = leitura\n"
            "    return marcadores\n",
        )

        assert offences(path) == []

    def test_an_english_comment_passes(self, tmp_path):
        path = self.write(
            tmp_path, "x = 1  # resolved per read, not in the constructor\n",
        )

        assert offences(path) == []

    @pytest.mark.parametrize("symbol", ["°C", "→", "—", "≤", "µs"])
    def test_the_symbols_english_comments_need_are_allowed(self, tmp_path, symbol):
        """
        Units and typography are not Portuguese. Banning every non-ASCII
        character would have forced "72.5 degrees C" and ASCII arrows into the
        pipeline diagrams.
        """
        path = self.write(tmp_path, f"x = 1  # threshold {symbol} here\n")

        assert offences(path) == []

    def test_the_allowed_symbols_do_not_overlap_the_banned_letters(self):
        assert not (ALLOWED_SYMBOLS & ACCENTED)

    def test_no_banned_word_is_also_english(self):
        """
        A word that is English too would fail honest comments. These three were
        in the list and came out.
        """
        for english in ("sensor", "thread", "normal", "total", "data"):
            assert english not in PORTUGUESE_WORDS
