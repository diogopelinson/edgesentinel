"""
Comandos de incidente no terminal: listar, reconhecer, resolver.

A transição acontece pelo store, não por memória compartilhada — é o que
torna possível reconhecer um incidente de outro processo enquanto o agente
roda, e é o que estes testes cobram junto com as mensagens de erro.
"""
import json
import time

import pytest

from adapters.store.sqlite import SQLiteEventStore
from cli.incidents import run_ack, run_incidents, run_resolve
from core.entities import Event
from core.incidents import Incident, IncidentState

HOUR = 3600


# --- helpers ---

@pytest.fixture
def workspace(tmp_path):
    """config.yaml apontando para um banco dentro de tmp_path."""
    db  = tmp_path / "data" / "events.db"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""
edgesentinel:
  sensors: []
  rules: []
  actions: []
  event_store:
    path: "{db.as_posix()}"
""", encoding="utf-8")
    return cfg, db


def make_incident(**overrides) -> Incident:
    fields = dict(rule_name="alta_temperatura", sensor_id="cpu_temp", severity="warning")
    fields.update(overrides)
    return Incident(**fields)


def seed(db, *incidents: Incident) -> list[Incident]:
    """Grava os incidentes e devolve com o id atribuído."""
    store = SQLiteEventStore(path=db)
    store.start()
    try:
        return [store.open_incident(i) for i in incidents]
    finally:
        store.close()


def seed_firings(db, incident_id: int, quantidade: int) -> None:
    store = SQLiteEventStore(path=db)
    store.start()
    try:
        for _ in range(quantidade):
            store.append(Event(
                rule_name="alta_temperatura", sensor_id="cpu_temp", value=82.0,
                unit="°C", severity="warning", incident_id=incident_id,
            ))
        assert store.flush()
    finally:
        store.close()


def estado(db, incident_id: int) -> IncidentState:
    store = SQLiteEventStore(path=db)
    return store.incident(incident_id).state


def stdout_lines(capsys) -> list[str]:
    return [linha for linha in capsys.readouterr().out.splitlines() if linha.strip()]


# --- listagem ---

class TestListing:

    def test_shows_state_severity_rule_and_duration(self, workspace, capsys):
        cfg, db = workspace
        agora = time.time()
        seed(db, make_incident(severity="critical", opened_at=agora - 2 * HOUR))

        assert run_incidents(cfg, now=agora) == 0

        saida = capsys.readouterr().out
        assert "alta_temperatura" in saida
        assert "cpu_temp" in saida
        assert "CRITICAL" in saida
        assert "TRIGGERED" in saida.upper()
        assert "2h" in saida, f"duração não aparece: {saida}"

    def test_counts_the_firings_of_each_incident(self, workspace, capsys):
        cfg, db = workspace
        (incidente,) = seed(db, make_incident())
        seed_firings(db, incidente.incident_id, 3)

        run_incidents(cfg)

        # a coluna de disparos mostra os três eventos agrupados
        assert "3" in capsys.readouterr().out

    def test_resolved_are_hidden_until_asked_for(self, workspace, capsys):
        cfg, db = workspace
        (aberto, resolvido) = seed(db, make_incident(rule_name="aberta"),
                                   make_incident(rule_name="resolvida"))
        run_resolve(cfg, resolvido.incident_id)
        capsys.readouterr()

        run_incidents(cfg)
        padrao = capsys.readouterr().out

        run_incidents(cfg, include_resolved=True)
        completo = capsys.readouterr().out

        assert "aberta" in padrao and "resolvida" not in padrao
        assert "aberta" in completo and "resolvida" in completo
        assert aberto.incident_id is not None

    @pytest.mark.parametrize("filtro,esperado,ausente", [
        ({"severity": "critical"}, "critica", "comum"),
        ({"rule": "comum"}, "comum", "critica"),
    ])
    def test_filters(self, workspace, capsys, filtro, esperado, ausente):
        cfg, db = workspace
        seed(db, make_incident(rule_name="critica", severity="critical"),
             make_incident(rule_name="comum", severity="warning"))

        run_incidents(cfg, **filtro)
        saida = capsys.readouterr().out

        assert esperado in saida
        assert ausente not in saida

    def test_window_filters_by_when_it_opened(self, workspace, capsys):
        cfg, db = workspace
        agora = time.time()
        seed(db, make_incident(rule_name="antiga", opened_at=agora - 48 * HOUR),
             make_incident(rule_name="recente", opened_at=agora - HOUR))

        run_incidents(cfg, window_seconds=24 * HOUR, now=agora)
        saida = capsys.readouterr().out

        assert "recente" in saida
        assert "antiga" not in saida

    def test_nothing_open_is_not_an_error(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_incident())
        run_resolve(cfg, 1)
        capsys.readouterr()

        assert run_incidents(cfg) == 0

        capturado = capsys.readouterr()
        assert capturado.out == ""
        assert "Nenhum incidente" in capturado.err

    def test_no_database_yet_is_not_an_error(self, workspace, capsys):
        cfg, _ = workspace

        assert run_incidents(cfg) == 0
        assert "não existe" in capsys.readouterr().err

    def test_a_disabled_store_is_an_error(self, tmp_path, capsys):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("""
edgesentinel:
  sensors: []
  rules: []
  actions: []
  event_store:
    enabled: false
""", encoding="utf-8")

        assert run_incidents(cfg) == 1
        assert "desabilitado" in capsys.readouterr().err


class TestJsonOutput:

    def test_one_object_per_line_with_the_whole_incident(self, workspace, capsys):
        cfg, db = workspace
        agora = time.time()
        (incidente,) = seed(db, make_incident(severity="critical", opened_at=agora - HOUR))
        seed_firings(db, incidente.incident_id, 2)

        assert run_incidents(cfg, as_json=True, now=agora) == 0

        registro = json.loads(stdout_lines(capsys)[0])
        assert registro["incident_id"] == incidente.incident_id
        assert registro["rule_name"] == "alta_temperatura"
        assert registro["sensor_id"] == "cpu_temp"
        assert registro["severity"] == "critical"
        assert registro["state"] == "triggered"
        assert registro["firings"] == 2
        assert registro["duration_seconds"] == pytest.approx(HOUR, abs=2)
        assert registro["acknowledged_at"] is None
        assert registro["resolved_at"] is None
        assert registro["opened"].startswith(time.strftime("%Y", time.localtime(agora - HOUR)))

    def test_stdout_holds_nothing_but_json(self, workspace, capsys):
        """Mensagem de status vai para o stderr — um pipe para jq não pode quebrar."""
        cfg, db = workspace
        seed(db, make_incident(severity="warning"))

        run_incidents(cfg, as_json=True, severity="critical")

        assert capsys.readouterr().out == ""


# --- transições ---

class TestAcknowledge:

    def test_ack_changes_the_state_in_the_store(self, workspace, capsys):
        cfg, db = workspace
        (incidente,) = seed(db, make_incident())

        assert run_ack(cfg, incidente.incident_id) == 0
        assert estado(db, incidente.incident_id) is IncidentState.ACKNOWLEDGED

    def test_ack_says_what_it_did(self, workspace, capsys):
        cfg, db = workspace
        (incidente,) = seed(db, make_incident())

        run_ack(cfg, incidente.incident_id)

        saida = capsys.readouterr().out
        assert str(incidente.incident_id) in saida
        assert "alta_temperatura" in saida

    def test_acknowledging_twice_is_not_an_error(self, workspace, capsys):
        """Idempotente de propósito: script que reconhece um id não pode falhar
        porque alguém reconheceu antes."""
        cfg, db = workspace
        (incidente,) = seed(db, make_incident())
        run_ack(cfg, incidente.incident_id)
        capsys.readouterr()

        assert run_ack(cfg, incidente.incident_id) == 0
        assert "já" in capsys.readouterr().err

    def test_acknowledging_a_resolved_incident_is_refused(self, workspace, capsys):
        """A máquina de estados não volta: resolvido não vira reconhecido."""
        cfg, db = workspace
        (incidente,) = seed(db, make_incident())
        run_resolve(cfg, incidente.incident_id)
        capsys.readouterr()

        assert run_ack(cfg, incidente.incident_id) == 1
        assert estado(db, incidente.incident_id) is IncidentState.RESOLVED
        assert "resolvido" in capsys.readouterr().err

    def test_an_unknown_id_is_a_message_not_a_traceback(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_incident())

        assert run_ack(cfg, 4242) == 1

        erro = capsys.readouterr().err
        assert "4242" in erro
        assert "Traceback" not in erro

    def test_no_database_is_an_error_for_a_transition(self, workspace, capsys):
        """Listar sem banco é 'nada ainda'; mudar estado sem banco é erro."""
        cfg, _ = workspace

        assert run_ack(cfg, 1) == 1
        assert "não existe" in capsys.readouterr().err


class TestResolve:

    def test_resolve_changes_the_state_and_stamps_the_time(self, workspace):
        cfg, db = workspace
        (incidente,) = seed(db, make_incident())

        assert run_resolve(cfg, incidente.incident_id) == 0

        store = SQLiteEventStore(path=db)
        lido = store.incident(incidente.incident_id)
        assert lido.state is IncidentState.RESOLVED
        assert lido.resolved_at is not None

    def test_resolving_an_acknowledged_incident_works(self, workspace, capsys):
        cfg, db = workspace
        (incidente,) = seed(db, make_incident())
        run_ack(cfg, incidente.incident_id)

        assert run_resolve(cfg, incidente.incident_id) == 0
        assert estado(db, incidente.incident_id) is IncidentState.RESOLVED

    def test_resolving_twice_is_not_an_error(self, workspace, capsys):
        cfg, db = workspace
        (incidente,) = seed(db, make_incident())
        run_resolve(cfg, incidente.incident_id)
        capsys.readouterr()

        assert run_resolve(cfg, incidente.incident_id) == 0
        assert "já" in capsys.readouterr().err

    def test_an_unknown_id_is_refused(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_incident())

        assert run_resolve(cfg, 99) == 1
        assert "99" in capsys.readouterr().err


class TestCommandLine:
    """Os três subcomandos no argparse: o que existe em run_* mas não na linha
    de comando é inalcançável pelo operador — o problema que esta feature
    resolve."""

    def _parse(self, *argv):
        import sys
        from unittest.mock import patch

        from cli.main import _parse_args
        with patch.object(sys, "argv", ["edgesentinel", *argv]):
            return _parse_args()

    def test_parses_every_option_of_the_listing(self):
        args = self._parse(
            "incidents", "--all", "--severity", "CRITICAL",
            "--rule", "alta_temperatura", "--last", "24h", "--limit", "5", "--json",
        )

        assert args.command == "incidents"
        assert args.all is True
        assert args.severity == "critical"
        assert args.rule == "alta_temperatura"
        assert args.last == 24 * HOUR
        assert args.limit == 5
        assert args.json is True

    def test_listing_defaults(self):
        args = self._parse("incidents")

        assert args.all is False
        assert args.severity is None
        assert args.last is None
        assert args.limit == 20
        assert args.json is False

    def test_ack_and_resolve_take_an_id(self):
        assert self._parse("ack", "7").incident_id == 7
        assert self._parse("resolve", "7").incident_id == 7

    @pytest.mark.parametrize("argv", [
        ("ack",),                       # sem id
        ("ack", "zero"),                # id não numérico
        ("ack", "0"),                   # id não é positivo
        ("resolve", "-3"),
        ("incidents", "--severity", "catastrophic"),
        ("incidents", "--last", "ontem"),
    ])
    def test_rejects_invalid_arguments(self, argv):
        with pytest.raises(SystemExit) as exc:
            self._parse(*argv)

        assert exc.value.code == 2

    def test_main_exits_with_the_command_status(self, tmp_path):
        import sys
        from unittest.mock import patch

        from cli.main import main
        argv = ["edgesentinel", "ack", "1", "--config", str(tmp_path / "nao_existe.yaml")]

        with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
