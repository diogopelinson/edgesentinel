#!/usr/bin/env python3
"""
Reports Portuguese comments and docstrings under the given paths.

The suite's own check (tests/test_code_language.py) scans the whole repository
and is the gate. This is the same logic pointed at a subtree, so that work in
progress can be verified a directory at a time.

Usage:
    python scripts/check_language.py core application
    python scripts/check_language.py            # the whole repository

Exits 1 when it finds something, so it can gate a loop.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from tests.test_code_language import SKIP, offences  # noqa: E402


def arquivos(alvos: list[str]) -> list[Path]:
    if not alvos:
        alvos = ["."]

    encontrados: list[Path] = []
    for alvo in alvos:
        caminho = (RAIZ / alvo).resolve()
        if caminho.is_file() and caminho.suffix == ".py":
            encontrados.append(caminho)
            continue
        encontrados.extend(
            p for p in caminho.rglob("*.py")
            if not any(parte in SKIP for parte in p.relative_to(RAIZ).parts)
        )
    return sorted(set(encontrados))


def main() -> int:
    alvos = sys.argv[1:]
    achados: list[str] = []
    for caminho in arquivos(alvos):
        achados.extend(offences(caminho))

    for linha in achados:
        print(linha)

    escopo = " ".join(alvos) if alvos else "(repositório)"
    print(f"\n{len(achados)} em {escopo}")
    return 1 if achados else 0


if __name__ == "__main__":
    sys.exit(main())
