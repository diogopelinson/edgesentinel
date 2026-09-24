#!/usr/bin/env python3
"""
Verificação de fumaça: sobe o agente de verdade e olha o que ele produziu.

A suíte de testes cobre funções; isto cobre o processo. Dois defeitos recentes
passaram por uma suíte verde e só apareceram quando alguém rodou o comando —
'python -m cli.main' não executava nada, e o simulate lia cada sensor duas
vezes por tick. Nenhum teste unitário pega essa classe de erro, porque nenhum
deles sobe o programa.

O que é verificado, em ordem:

  1. o agente sobe com um config escrito agora e não morre nos primeiros segundos
  2. o endpoint de métricas responde e traz a métrica de leitura de sensor
  3. uma regra dispara, o evento vai para o banco e um incidente é aberto
  4. SIGTERM — o sinal que systemd e Docker enviam — encerra com código 0
  5. o que estava na fila foi gravado antes de sair

Uso:
    python scripts/smoke.py [--seconds 20]

Precisa de Linux: usa /proc para os sensores e sinais POSIX para o encerramento.
Em outra plataforma, avisa e sai com 0 — quem roda isso de verdade é o CI.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

CONFIG = """
edgesentinel:
  poll_interval_seconds: 1

  sensors:
    - id: cpu_usage
      type: cpu_usage
    - id: memory_usage
      type: memory_usage

  inference:
    enabled: false

  exporter:
    port: {porta}

  event_store:
    enabled: true
    path: "{banco}"
    retention_days: 1

  rules:
    # dispara em qualquer leitura: a verificação é do processo, não do limiar
    - name: smoke_memoria
      condition:
        sensor_id: memory_usage
        operator: ">"
        threshold: 0.0
      severity: warning
      cooldown_seconds: 0
      actions: [log]

  actions:
    - id: log
      type: log
"""


class Falha(Exception):
    """Uma verificação não passou. A mensagem é o relatório."""


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def espera(descricao: str, condicao, limite: float) -> float:
    """Espera a condição virar verdadeira. Devolve quanto tempo levou."""
    inicio = time.monotonic()
    while time.monotonic() - inicio < limite:
        with contextlib.suppress(Exception):
            if condicao():
                return time.monotonic() - inicio
        time.sleep(0.3)
    raise Falha(f"{descricao}: nada em {limite:.0f}s")


def metricas(porta: int) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{porta}/metrics", timeout=2) as resposta:
        return resposta.read().decode()


def conta(banco: Path, tabela: str) -> int:
    if not banco.exists():
        return 0
    # somente leitura: a fumaça não escreve no banco do agente
    con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0])
    finally:
        con.close()


def roda(segundos: float) -> list[str]:
    """Sobe o agente, verifica, encerra. Devolve as linhas do relatório."""
    relatorio: list[str] = []
    trabalho = Path(tempfile.mkdtemp(prefix="edgesentinel-smoke-"))
    banco = trabalho / "smoke.db"
    porta = porta_livre()
    config = trabalho / "smoke.yaml"
    config.write_text(CONFIG.format(porta=porta, banco=banco.as_posix()), encoding="utf-8")
    log = (trabalho / "agente.log").open("w", encoding="utf-8")

    processo = subprocess.Popen(
        [sys.executable, "-m", "cli.main", "run", "--config", str(config)],
        cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
    )

    def relata(item: str) -> None:
        relatorio.append(item)
        print(f"  OK   {item}", flush=True)

    try:
        # 1. sobe e continua vivo
        time.sleep(2)
        if processo.poll() is not None:
            raise Falha(
                f"o agente saiu com código {processo.returncode} nos primeiros "
                f"segundos:\n{(trabalho / 'agente.log').read_text(encoding='utf-8')}"
            )
        relata("o agente continua rodando depois de subir")

        # 2. métricas
        levou = espera("endpoint de métricas", lambda: "edgesentinel_sensor_value" in metricas(porta), segundos)
        relata(f"/metrics responde com edgesentinel_sensor_value ({levou:.1f}s)")

        # 3. evento e incidente no banco
        levou = espera("evento no histórico", lambda: conta(banco, "events") > 0, segundos)
        relata(f"a regra disparou e o evento foi gravado ({levou:.1f}s)")

        levou = espera("incidente aberto", lambda: conta(banco, "incidents") > 0, segundos)
        relata(f"o disparo abriu um incidente ({levou:.1f}s)")

        antes = conta(banco, "events")

        # 4. SIGTERM: o sinal de systemd e Docker, não Ctrl+C
        processo.terminate()
        try:
            codigo = processo.wait(timeout=15)
        except subprocess.TimeoutExpired:
            processo.kill()
            raise Falha("o agente não encerrou 15s depois do SIGTERM") from None

        if codigo != 0:
            raise Falha(
                f"SIGTERM encerrou com código {codigo}, não 0:\n"
                f"{(trabalho / 'agente.log').read_text(encoding='utf-8')[-2000:]}"
            )
        relata("SIGTERM encerrou o agente com código 0")

        # 5. nada se perdeu no caminho
        depois = conta(banco, "events")
        if depois < antes:
            raise Falha(f"o histórico encolheu no encerramento: {antes} -> {depois}")
        relata(f"histórico preservado no encerramento ({depois} evento(s))")

        saida = (trabalho / "agente.log").read_text(encoding="utf-8")
        if "encerrado" not in saida:
            raise Falha("o log não registra o encerramento do agente")
        relata("o encerramento aparece no log")

        # 6. todo disparo que o engine anunciou tem de estar no banco: pega
        # thread de escrita morta ou store engolindo evento em silêncio.
        #
        # Não pega um close() que deixou de gravar a fila — a thread drena em
        # lote continuamente, então no instante do SIGTERM a fila já está
        # vazia e nada se perde. Essa garantia é de
        # tests/adapters/test_sqlite_store.py::test_close_waits_for_queued_events_to_be_written,
        # que provoca a condição com uma escrita lenta. Verificado por mutação:
        # desligar o close() daqui não faz esta verificação falhar.
        disparos = sum(1 for linha in saida.splitlines() if "engine: Regra" in linha)
        if disparos == 0:
            raise Falha("o log não mostra nenhum disparo — a regra de fumaça não rodou")
        if depois < disparos:
            raise Falha(
                f"{disparos} disparo(s) no log, {depois} evento(s) no banco: "
                f"a fila não foi gravada no encerramento"
            )
        relata(f"todo disparo anunciado está no histórico ({disparos} = {depois})")

        return relatorio
    finally:
        if processo.poll() is None:
            processo.kill()
        log.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificação de fumaça do agente")
    parser.add_argument("--seconds", type=float, default=20.0,
                        help="quanto esperar por cada verificação (padrão: 20)")
    args = parser.parse_args()

    if os.name != "posix":
        print("SKIP: esta verificação precisa de Linux (/proc e sinais POSIX).")
        return 0

    print("verificação de fumaça — subindo o agente de verdade\n")
    try:
        relatorio = roda(args.seconds)
    except Falha as e:
        print(f"\nFALHOU  {e}", file=sys.stderr)
        return 1

    print(f"\n{len(relatorio)} verificação(ões) passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
