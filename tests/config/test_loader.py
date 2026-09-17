import pytest
from pathlib import Path

from config.loader import load


def test_loads_valid_config(tmp_path):
    """tmp_path é uma fixture nativa do pytest — cria pasta temporária."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
edgesentinel:
  poll_interval_seconds: 10
  sensors:
    - id: cpu_temp
      type: cpu_temperature
  inference:
    enabled: false
  exporter:
    port: 9000
  rules:
    - name: alta_temp
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 75.0
      actions: [log]
  actions:
    - id: log
      type: log
""")

    config = load(config_file)

    assert config.poll_interval_seconds == 10
    assert len(config.sensors) == 1
    assert config.sensors[0].id == "cpu_temp"
    assert config.exporter.port == 9000
    assert config.inference.enabled is False
    assert len(config.rules) == 1
    assert config.rules[0].name == "alta_temp"
    assert config.rules[0].condition.threshold == 75.0


def test_raises_when_file_not_found():
    with pytest.raises(FileNotFoundError):
        load("/caminho/que/nao/existe/config.yaml")


def test_raises_when_missing_root_key(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("outro_sistema:\n  foo: bar\n")

    with pytest.raises(ValueError, match="edgesentinel"):
        load(config_file)


def test_raises_when_sensor_missing_id(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
edgesentinel:
  sensors:
    - type: cpu_temperature
  rules: []
  actions: []
""")

    with pytest.raises(ValueError, match="id"):
        load(config_file)


def test_defaults_are_applied(tmp_path):
    """Config mínimo deve usar valores padrão."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
edgesentinel:
  sensors:
    - id: cpu_temp
      type: cpu_temperature
  rules: []
  actions: []
""")

    config = load(config_file)

    assert config.poll_interval_seconds == 5.0
    assert config.exporter.port == 8000
    assert config.inference.enabled is False
    assert config.inference.backend == "dummy"


def _config_with_rule_severity(tmp_path, severity_line: str) -> Path:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"""
edgesentinel:
  sensors:
    - id: cpu_temp
      type: cpu_temperature
  rules:
    - name: alta_temp
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 75.0
      actions: [log]
{severity_line}
  actions:
    - id: log
      type: log
""")
    return config_file


@pytest.mark.parametrize("declared", ["info", "warning", "critical"])
def test_parses_each_severity_level(tmp_path, declared):
    config = load(_config_with_rule_severity(tmp_path, f"      severity: {declared}"))

    assert config.rules[0].severity == declared


def test_severity_defaults_to_warning_when_omitted(tmp_path):
    """Nenhum config existente declara severity — todos devem seguir válidos."""
    config = load(_config_with_rule_severity(tmp_path, ""))

    assert config.rules[0].severity == "warning"


def test_severity_is_case_insensitive(tmp_path):
    config = load(_config_with_rule_severity(tmp_path, "      severity: CRITICAL"))

    assert config.rules[0].severity == "critical"


def test_raises_on_unknown_severity(tmp_path):
    """
    Severity inválida precisa falhar no carregamento, não no primeiro disparo
    da regra — que pode acontecer dias depois, em campo.
    """
    config_file = _config_with_rule_severity(tmp_path, "      severity: catastrophic")

    with pytest.raises(ValueError) as exc:
        load(config_file)

    message = str(exc.value)
    assert "catastrophic" in message
    assert "alta_temp" in message


def _config_with_event_store(tmp_path, section: str) -> Path:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"""
edgesentinel:
  sensors:
    - id: cpu_temp
      type: cpu_temperature
  rules: []
  actions: []
{section}
""", encoding="utf-8")
    return config_file


def test_event_store_is_enabled_by_default(tmp_path):
    """Histórico sem configuração nenhuma — o banco nasce na primeira execução."""
    config = load(_config_with_event_store(tmp_path, ""))

    assert config.event_store.enabled is True
    assert config.event_store.path == "data/events.db"
    assert config.event_store.retention_days == 30.0


def test_parses_the_event_store_section(tmp_path):
    config = load(_config_with_event_store(tmp_path, """
  event_store:
    enabled: false
    path: /var/lib/edgesentinel/events.db
    retention_days: 7
"""))

    assert config.event_store.enabled is False
    assert config.event_store.path == "/var/lib/edgesentinel/events.db"
    assert config.event_store.retention_days == 7.0


@pytest.mark.parametrize("retention", ["0", "-5"])
def test_rejects_non_positive_retention(tmp_path, retention):
    """
    Retenção zero apagaria o histórico inteiro a cada inicialização — é
    quase certamente um erro de digitação, não uma intenção.
    """
    config_file = _config_with_event_store(tmp_path, f"""
  event_store:
    retention_days: {retention}
""")

    with pytest.raises(ValueError, match="retention_days"):
        load(config_file)