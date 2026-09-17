import json
import sys
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from adapters.store.sqlite import SQLiteEventStore
from cli.events import parse_duration, run_events
from core.entities import Event

HOUR = 3600
DAY  = 24 * HOUR


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


def make_event(**overrides) -> Event:
    fields = dict(
        rule_name="alta_temperatura",
        sensor_id="cpu_temp",
        value=78.5,
        unit="°C",
        severity="warning",
        timestamp=time.time() - 60,
    )
    fields.update(overrides)
    return Event(**fields)


def seed(db, *events: Event) -> None:
    store = SQLiteEventStore(path=db)
    store.start()
    for event in events:
        store.append(event)
    store.close()


def stdout_lines(capsys) -> list[str]:
    return [line for line in capsys.readouterr().out.splitlines() if line.strip()]


class TestParseDuration:

    @pytest.mark.parametrize("text, seconds", [
        ("45s", 45),
        ("30m", 30 * 60),
        ("24h", DAY),
        ("7d",  7 * DAY),
        ("24H", DAY),
    ])
    def test_converts_to_seconds(self, text, seconds):
        assert parse_duration(text) == seconds

    @pytest.mark.parametrize("text", ["", "24", "h", "1.5h", "-3h", "10x", "0h"])
    def test_rejects_invalid_durations(self, text):
        with pytest.raises(ValueError):
            parse_duration(text)

    def test_error_shows_valid_examples(self):
        with pytest.raises(ValueError, match="30m"):
            parse_duration("ontem")


class TestTableOutput:

    def test_lists_newest_first(self, workspace, capsys):
        cfg, db = workspace
        seed(db,
             make_event(rule_name="primeira", timestamp=time.time() - 2 * HOUR),
             make_event(rule_name="segunda",  timestamp=time.time() - HOUR))

        assert run_events(cfg) == 0

        out = capsys.readouterr().out
        assert out.index("segunda") < out.index("primeira")

    def test_shows_severity_value_and_unit(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_event(severity="critical", value=91.2, unit="°C"))

        run_events(cfg)

        out = capsys.readouterr().out
        assert "CRITICAL" in out
        assert "91.20 °C" in out

    def test_shows_a_dash_when_there_is_no_anomaly_score(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_event(anomaly_score=None))

        run_events(cfg)

        row = stdout_lines(capsys)[1]
        assert row.rstrip().endswith("-")

    def test_shows_the_anomaly_score_when_present(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_event(anomaly_score=0.934))

        run_events(cfg)

        assert "0.93" in capsys.readouterr().out

    def test_footer_counts_the_events(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_event(), make_event())

        run_events(cfg)

        assert "2 evento(s)" in capsys.readouterr().out

    def test_footer_points_to_limit_when_results_were_cut(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_event(), make_event(), make_event())

        run_events(cfg, limit=2)

        out = capsys.readouterr().out
        assert "2 evento(s)" in out
        assert "--limit" in out

    def test_no_color_when_output_is_not_a_terminal(self, workspace, capsys):
        """Redirecionado para arquivo ou pipe, escape ANSI vira lixo."""
        cfg, db = workspace
        seed(db, make_event(severity="critical"))

        run_events(cfg)

        assert "\033[" not in capsys.readouterr().out


class TestFilters:

    def test_by_severity(self, workspace, capsys):
        cfg, db = workspace
        seed(db,
             make_event(rule_name="aviso",   severity="warning"),
             make_event(rule_name="critica", severity="critical"))

        run_events(cfg, severity="critical")

        out = capsys.readouterr().out
        assert "critica" in out
        assert "aviso" not in out

    def test_by_sensor(self, workspace, capsys):
        cfg, db = workspace
        seed(db,
             make_event(rule_name="temp", sensor_id="cpu_temp"),
             make_event(rule_name="mem",  sensor_id="memory_usage"))

        run_events(cfg, sensor="memory_usage")

        out = capsys.readouterr().out
        assert "mem" in out
        assert "temp" not in out

    def test_by_rule(self, workspace, capsys):
        cfg, db = workspace
        seed(db,
             make_event(rule_name="alta_temperatura"),
             make_event(rule_name="uso_alto_cpu"))

        run_events(cfg, rule="uso_alto_cpu")

        out = capsys.readouterr().out
        assert "uso_alto_cpu" in out
        assert "alta_temperatura" not in out

    def test_by_time_window(self, workspace, capsys):
        cfg, db = workspace
        now = time.time()
        seed(db,
             make_event(rule_name="recente", timestamp=now - 2 * HOUR),
             make_event(rule_name="antiga",  timestamp=now - 2 * DAY))

        run_events(cfg, window_seconds=DAY, now=now)

        out = capsys.readouterr().out
        assert "recente" in out
        assert "antiga" not in out

    def test_filters_combine(self, workspace, capsys):
        cfg, db = workspace
        now = time.time()
        seed(db,
             make_event(rule_name="alvo",         severity="critical", timestamp=now - HOUR),
             make_event(rule_name="fora_janela",  severity="critical", timestamp=now - 3 * DAY),
             make_event(rule_name="outro_nivel",  severity="warning",  timestamp=now - HOUR))

        run_events(cfg, severity="critical", window_seconds=DAY, now=now)

        out = capsys.readouterr().out
        assert "alvo" in out
        assert "fora_janela" not in out
        assert "outro_nivel" not in out

    def test_empty_result_is_not_an_error(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_event(severity="warning"))

        assert run_events(cfg, severity="critical") == 0

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Nenhum evento" in captured.err


class TestJsonOutput:

    def test_emits_one_json_object_per_line(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_event(rule_name="a"), make_event(rule_name="b"))

        assert run_events(cfg, as_json=True) == 0

        records = [json.loads(line) for line in stdout_lines(capsys)]
        assert len(records) == 2

    def test_record_carries_every_event_field(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_event(
            rule_name="temperatura_critica", sensor_id="cpu_temp",
            value=91.2, unit="°C", severity="critical", anomaly_score=0.93,
        ))

        run_events(cfg, as_json=True)

        record = json.loads(stdout_lines(capsys)[0])
        assert record["rule_name"]     == "temperatura_critica"
        assert record["sensor_id"]     == "cpu_temp"
        assert record["value"]         == pytest.approx(91.2)
        assert record["unit"]          == "°C"
        assert record["severity"]      == "critical"
        assert record["anomaly_score"] == pytest.approx(0.93)
        assert isinstance(record["event_id"], int)
        assert isinstance(record["timestamp"], float)

    def test_record_has_a_readable_time_with_offset(self, workspace, capsys):
        cfg, db = workspace
        seed(db, make_event())

        run_events(cfg, as_json=True)

        record = json.loads(stdout_lines(capsys)[0])
        parsed = datetime.fromisoformat(record["time"])
        assert parsed.tzinfo is not None
        assert parsed.timestamp() == pytest.approx(record["timestamp"], abs=1)

    def test_stdout_holds_nothing_but_json(self, workspace, capsys):
        """Mensagens de status vão para o stderr — um pipe para jq não pode quebrar."""
        cfg, db = workspace
        seed(db, make_event(severity="warning"))

        run_events(cfg, as_json=True, severity="critical")

        assert capsys.readouterr().out == ""


class TestStoreState:

    def test_missing_database_is_reported_and_not_created(self, workspace, capsys):
        cfg, db = workspace

        assert run_events(cfg) == 0

        assert "Nenhum evento registrado" in capsys.readouterr().err
        assert not db.exists()

    def test_reading_never_prunes_old_history(self, workspace, capsys):
        """Consultar é só leitura — retenção é assunto de quem grava."""
        cfg, db = workspace
        seed(db, make_event(rule_name="de_40_dias", timestamp=time.time() - 40 * DAY))

        run_events(cfg)

        assert "de_40_dias" in capsys.readouterr().out

    def test_disabled_store_is_an_error(self, tmp_path, capsys):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("""
edgesentinel:
  sensors: []
  rules: []
  actions: []
  event_store:
    enabled: false
""", encoding="utf-8")

        assert run_events(cfg) == 1
        assert "desabilitado" in capsys.readouterr().err

    def test_missing_config_is_an_error(self, tmp_path, capsys):
        assert run_events(tmp_path / "nao_existe.yaml") == 1
        assert "Erro" in capsys.readouterr().err

    def test_unreadable_database_is_an_error(self, workspace, capsys):
        cfg, db = workspace
        db.parent.mkdir(parents=True)
        db.write_text("isto não é um banco sqlite", encoding="utf-8")

        assert run_events(cfg) == 1
        assert str(db.name) in capsys.readouterr().err


class TestCommandLine:

    def _parse(self, *argv):
        from cli.main import _parse_args
        with patch.object(sys, "argv", ["edgesentinel", *argv]):
            return _parse_args()

    def test_parses_every_option(self):
        args = self._parse(
            "events", "--severity", "CRITICAL", "--sensor", "cpu_temp",
            "--rule", "alta_temperatura", "--last", "24h", "--limit", "5", "--json",
        )

        assert args.command  == "events"
        assert args.severity == "critical"
        assert args.sensor   == "cpu_temp"
        assert args.rule     == "alta_temperatura"
        assert args.last     == DAY
        assert args.limit    == 5
        assert args.json is True

    def test_defaults(self):
        args = self._parse("events")

        assert args.severity is None
        assert args.last is None
        assert args.limit == 20
        assert args.json is False

    @pytest.mark.parametrize("argv", [
        ("events", "--last", "ontem"),
        ("events", "--limit", "0"),
        ("events", "--severity", "catastrophic"),
    ])
    def test_rejects_invalid_arguments(self, argv, capsys):
        with pytest.raises(SystemExit) as exc:
            self._parse(*argv)

        assert exc.value.code == 2

    def test_main_exits_with_the_command_status(self, tmp_path):
        from cli.main import main
        argv = ["edgesentinel", "events", "--config", str(tmp_path / "nao_existe.yaml")]

        with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
