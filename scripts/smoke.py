#!/usr/bin/env python3
"""
Smoke check: boots the real agent and looks at what it produced.

The test suite covers functions; this covers the program. Two recent defects got
through a green suite and only showed up when someone ran the command —
`python -m cli.main` executed nothing at all, and simulate read every sensor
twice per tick. No unit test catches that class of error, because none of them
start the program.

What is checked, in order:

  1. the agent comes up with a config written just now and does not die in the
     first few seconds
  2. the metrics endpoint answers and carries the sensor reading metric
  3. a rule fires, the event reaches the database and an incident is opened
  4. the open incident appears on /metrics, with the right rule and severity
  5. SIGTERM — the signal systemd and Docker send — exits with code 0
  6. whatever was queued was written before leaving

Usage:
    python scripts/smoke.py [--seconds 20]

Needs Linux: it uses /proc for the sensors and POSIX signals for the shutdown.
On any other platform it says so and exits 0 — what really runs this is CI.
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
    """A check did not pass. The message is the report."""


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def espera(descricao: str, condicao, limite: float) -> float:
    """Waits for the condition to hold. Returns how long it took."""
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
    # read-only: the smoke check does not write to the agent's database
    con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0])
    finally:
        con.close()


def roda(segundos: float) -> list[str]:
    """Boots the agent, checks it, shuts it down. Returns the report lines."""
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

        # 2. the metrics
        levou = espera("endpoint de métricas", lambda: "edgesentinel_sensor_value" in metricas(porta), segundos)
        relata(f"/metrics responde com edgesentinel_sensor_value ({levou:.1f}s)")

        # 3. event and incident in the database
        levou = espera("evento no histórico", lambda: conta(banco, "events") > 0, segundos)
        relata(f"a regra disparou e o evento foi gravado ({levou:.1f}s)")

        levou = espera("incidente aberto", lambda: conta(banco, "incidents") > 0, segundos)
        relata(f"o disparo abriu um incidente ({levou:.1f}s)")

        # 4. the open gauge is read from the database during the scrape, so it
        # only appears if the builder -> exporter -> store wiring is standing.
        # No unit test catches this: every piece passes on its own while the
        # exporter in the real process has no store to query
        alvo = 'edgesentinel_incidents_open{rule="smoke_memoria",severity="warning",state="triggered"} 1.0'
        levou = espera("incidente no /metrics", lambda: alvo in metricas(porta), segundos)
        relata(f"o incidente aberto aparece no /metrics ({levou:.1f}s)")

        if "edgesentinel_incidents_total" not in metricas(porta):
            raise Falha(
                "o incidente abriu e edgesentinel_incidents_total não apareceu "
                "— o engine não está contabilizando a transição."
            )
        relata("a abertura foi contabilizada em edgesentinel_incidents_total")

        antes = conta(banco, "events")

        # 5. SIGTERM: the signal systemd and Docker send, not Ctrl+C
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

        # 6. nothing was lost on the way
        depois = conta(banco, "events")
        if depois < antes:
            raise Falha(f"o histórico encolheu no encerramento: {antes} -> {depois}")
        relata(f"histórico preservado no encerramento ({depois} evento(s))")

        saida = (trabalho / "agente.log").read_text(encoding="utf-8")
        if "encerrado" not in saida:
            raise Falha("o log não registra o encerramento do agente")
        relata("o encerramento aparece no log")

        # 6. every firing the engine announced has to be in the database: this
        # catches a dead writer thread, or a store swallowing events silently.
        #
        # It does not catch a close() that stopped writing the queue — the
        # thread drains in batches continuously, so at the instant of the
        # SIGTERM the queue is already empty and nothing is lost. That
        # guarantee belongs to
        # tests/adapters/test_sqlite_store.py::test_close_waits_for_queued_events_to_be_written,
        # which provokes the condition with a slow write. Mutation-checked:
        # disabling close() here does not make this check fail.
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
