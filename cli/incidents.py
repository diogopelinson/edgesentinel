"""
Comandos de incidente: listar, reconhecer, resolver.

A transição acontece pelo store, e não por um canal com o processo que está
monitorando. Isso não é detalhe de implementação: é a prova de que o estado é
persistido. O agente lê os incidentes abertos a cada avaliação, então um
reconhecimento feito aqui vale no ciclo seguinte dele, sem sinal e sem
restart.

Como no comando de eventos, stdout recebe só dados — tabela ou JSON Lines — e
mensagem de status vai para o stderr.
"""
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from adapters.store.sqlite import SQLiteEventStore
from cli.render import COLORS, RESET, human_duration
from cli.store import StoreIndisponivel, store_path
from core.incidents import Incident, IncidentState

_HEADERS     = ("#", "ESTADO", "SEVERIDADE", "REGRA", "SENSOR", "ABERTO", "DURAÇÃO", "DISPAROS")
_RIGHT_ALIGN = {0, 7}

# como cada estado é anunciado ao operador
_PARTICIPIO = {
    IncidentState.ACKNOWLEDGED: "reconhecido",
    IncidentState.RESOLVED:     "resolvido",
}


def run_incidents(
    config_path: str | Path,
    *,
    include_resolved: bool = False,
    severity: str | None = None,
    rule: str | None = None,
    window_seconds: float | None = None,
    limit: int = 20,
    as_json: bool = False,
    now: float | None = None,
) -> int:
    """Lista incidentes. Devolve o código de saída."""
    try:
        path = store_path(config_path)
    except StoreIndisponivel as e:
        _status(str(e))
        return 1

    if not path.exists():
        # checado antes de abrir: sqlite3.connect criaria um arquivo vazio
        _status(f"Nenhum incidente registrado ainda — {path} não existe.")
        return 0

    agora = time.time() if now is None else now
    since = None if window_seconds is None else agora - window_seconds

    # sem start(): ele aplica a retenção e sobe a thread de escrita, e
    # consultar não pode apagar nada nem deixar thread para trás
    store = SQLiteEventStore(path=path)
    try:
        incidentes = store.incidents(
            include_resolved=include_resolved,
            severity=severity,
            rule_name=rule,
            since=since,
            limit=limit,
        )
        disparos = store.firings([i.incident_id for i in incidentes if i.incident_id])
    except sqlite3.Error as e:
        _status(f"Erro: não foi possível ler {path}: {e}")
        return 1

    if as_json:
        for incidente in incidentes:
            print(json.dumps(_to_record(incidente, disparos, agora), ensure_ascii=False))
        if not incidentes:
            _status(_nada_encontrado(include_resolved))
        return 0

    if not incidentes:
        _status(_nada_encontrado(include_resolved))
        return 0

    print(format_table(incidentes, disparos, agora, color=sys.stdout.isatty()))
    print()
    print(_footer(len(incidentes), limit, include_resolved))
    return 0


def run_ack(config_path: str | Path, incident_id: int, *, now: float | None = None) -> int:
    """Marca como reconhecido: alguém viu, o problema continua."""
    return _transition(config_path, incident_id, IncidentState.ACKNOWLEDGED, now)


def run_resolve(config_path: str | Path, incident_id: int, *, now: float | None = None) -> int:
    """Fecha o incidente à mão, sem esperar a leitura recuar."""
    return _transition(config_path, incident_id, IncidentState.RESOLVED, now)


def format_table(
    incidentes: list[Incident],
    disparos: dict[int, int],
    agora: float,
    color: bool = False,
) -> str:
    linhas = [
        (
            str(incidente.incident_id),
            incidente.state.value.upper(),
            incidente.severity.upper(),
            incidente.rule_name,
            incidente.sensor_id,
            datetime.fromtimestamp(incidente.opened_at).strftime("%Y-%m-%d %H:%M:%S"),
            human_duration(_duration(incidente, agora)),
            str(disparos.get(incidente.incident_id or 0, 0)),
        )
        for incidente in incidentes
    ]

    larguras = [
        max(len(cabecalho), *(len(linha[coluna]) for linha in linhas)) if linhas else len(cabecalho)
        for coluna, cabecalho in enumerate(_HEADERS)
    ]

    def render(celulas: tuple[str, ...], severidade: str | None = None) -> str:
        alinhadas = [
            celula.rjust(largura) if coluna in _RIGHT_ALIGN else celula.ljust(largura)
            for coluna, (celula, largura) in enumerate(zip(celulas, larguras, strict=True))
        ]
        # cor aplicada depois do alinhamento: escape ANSI não ocupa coluna
        if color and severidade in COLORS:
            alinhadas[2] = f"{COLORS[severidade]}{alinhadas[2]}{RESET}"
        return "  ".join(alinhadas).rstrip()

    return "\n".join([
        render(_HEADERS),
        *(render(linha, incidente.severity)
          for linha, incidente in zip(linhas, incidentes, strict=True)),
    ])


# --- privados ---

def _transition(
    config_path: str | Path,
    incident_id: int,
    alvo: IncidentState,
    now: float | None,
) -> int:
    try:
        path = store_path(config_path)
    except StoreIndisponivel as e:
        _status(str(e))
        return 1

    if not path.exists():
        # diferente da listagem: mudar estado do que não existe é erro
        _status(f"Erro: {path} não existe — nenhum incidente foi registrado ainda.")
        return 1

    store = SQLiteEventStore(path=path)
    try:
        incidente = store.incident(incident_id)
    except sqlite3.Error as e:
        _status(f"Erro: não foi possível ler {path}: {e}")
        return 1

    if incidente is None:
        _status(
            f"Erro: não existe incidente #{incident_id}. "
            f"Use 'edgesentinel incidents' para ver os abertos."
        )
        return 1

    if incidente.state is alvo:
        # idempotente: script que reconhece um id não falha porque alguém
        # reconheceu antes
        _status(f"Incidente #{incident_id} já está {_PARTICIPIO[alvo]}.")
        return 0

    if incidente.state is IncidentState.RESOLVED:
        _status(
            f"Erro: incidente #{incident_id} já foi resolvido — o ciclo não "
            f"volta atrás. O próximo disparo da regra abre outro."
        )
        return 1

    quando = time.time() if now is None else now
    try:
        if alvo is IncidentState.ACKNOWLEDGED:
            store.acknowledge_incident(incident_id, at=quando)
        else:
            store.resolve_incident(incident_id, at=quando)
    except sqlite3.Error as e:
        _status(f"Erro: não foi possível atualizar {path}: {e}")
        return 1

    print(
        f"Incidente #{incident_id} de '{incidente.rule_name}' "
        f"[{incidente.severity}] {_PARTICIPIO[alvo]} "
        f"após {human_duration(quando - incidente.opened_at)} aberto."
    )
    if alvo is IncidentState.ACKNOWLEDGED:
        _status("O agente para de repetir as ações dessa regra no próximo ciclo; "
                "os disparos continuam indo para o histórico.")
    return 0


def _duration(incidente: Incident, agora: float) -> float:
    fim = incidente.resolved_at if incidente.resolved_at is not None else agora
    return fim - incidente.opened_at


def _to_record(incidente: Incident, disparos: dict[int, int], agora: float) -> dict:
    local = datetime.fromtimestamp(incidente.opened_at).astimezone()
    return {
        "incident_id":      incidente.incident_id,
        "state":            incidente.state.value,
        "severity":         incidente.severity,
        "rule_name":        incidente.rule_name,
        "sensor_id":        incidente.sensor_id,
        "opened":           local.isoformat(timespec="seconds"),
        "opened_at":        incidente.opened_at,
        "acknowledged_at":  incidente.acknowledged_at,
        "resolved_at":      incidente.resolved_at,
        "duration_seconds": round(_duration(incidente, agora), 3),
        "firings":          disparos.get(incidente.incident_id or 0, 0),
    }


def _nada_encontrado(include_resolved: bool) -> str:
    if include_resolved:
        return "Nenhum incidente encontrado com esses filtros."
    return (
        "Nenhum incidente aberto. Use --all para ver os resolvidos também."
    )


def _footer(quantidade: int, limit: int, include_resolved: bool) -> str:
    escopo = "incidente(s)" if include_resolved else "incidente(s) aberto(s)"
    if quantidade < limit:
        return f"{quantidade} {escopo}"
    return f"{quantidade} {escopo} — limite de {limit} atingido; use --limit para ver mais"


def _status(mensagem: str) -> None:
    print(mensagem, file=sys.stderr)
