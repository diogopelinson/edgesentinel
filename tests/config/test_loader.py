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


# --- default_actions e o campo actions das regras ---

def _config_with(tmp_path, rules_yaml: str, extra_yaml: str = "") -> Path:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"""
edgesentinel:
  sensors:
    - id: cpu_temp
      type: cpu_temperature
{extra_yaml}
  rules:
{rules_yaml}
  actions:
    - id: log
      type: log
    - id: webhook
      type: webhook
      url: https://hooks.exemplo.com/alerta
""", encoding="utf-8")
    return config_file


_RULE_HEAD = """    - name: alta_temp
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 75.0
"""


def test_rule_without_actions_is_left_undeclared(tmp_path):
    """None, não lista vazia: é o que permite ao mapper aplicar default_actions."""
    config = load(_config_with(tmp_path, _RULE_HEAD))

    assert config.rules[0].actions is None


def test_explicit_empty_actions_are_kept_as_empty(tmp_path):
    """`actions: []` é uma escolha — só registrar no histórico — e não pode virar 'usar o padrão'."""
    config = load(_config_with(tmp_path, _RULE_HEAD + "      actions: []\n"))

    assert config.rules[0].actions == []


def test_default_actions_are_absent_by_default(tmp_path):
    config = load(_config_with(tmp_path, _RULE_HEAD + "      actions: [log]\n"))

    assert config.default_actions == {}


def test_parses_default_actions_by_severity(tmp_path):
    config = load(_config_with(tmp_path, _RULE_HEAD, """
  default_actions:
    warning:  [log]
    CRITICAL: [log, webhook]
"""))

    assert config.default_actions == {
        "warning":  ["log"],
        "critical": ["log", "webhook"],
    }


def test_rejects_an_unknown_severity_in_default_actions(tmp_path):
    config_file = _config_with(tmp_path, _RULE_HEAD, """
  default_actions:
    critcal: [log]
""")

    with pytest.raises(ValueError) as exc:
        load(config_file)

    message = str(exc.value)
    assert "default_actions" in message
    assert "critcal" in message


def test_rejects_default_actions_that_are_not_a_list(tmp_path):
    config_file = _config_with(tmp_path, _RULE_HEAD, """
  default_actions:
    warning: log
""")

    with pytest.raises(ValueError, match="default_actions"):
        load(config_file)


def test_rejects_default_actions_that_are_not_a_mapping(tmp_path):
    config_file = _config_with(tmp_path, _RULE_HEAD, """
  default_actions: [log, webhook]
""")

    with pytest.raises(ValueError, match="default_actions"):
        load(config_file)


def test_rejects_the_same_severity_twice_in_default_actions(tmp_path):
    """'warning' e 'Warning' viram a mesma chave — um dos dois seria descartado em silêncio."""
    config_file = _config_with(tmp_path, _RULE_HEAD, """
  default_actions:
    warning: [log]
    Warning: [webhook]
""")

    with pytest.raises(ValueError, match="warning"):
        load(config_file)


def test_rejects_rule_actions_written_as_a_severity_map(tmp_path):
    """
    Uma regra tem uma severidade só — um mapa por severidade dentro dela não
    faz sentido. O erro precisa apontar para onde esse mapa vai.
    """
    config_file = _config_with(tmp_path, _RULE_HEAD + """      actions:
        critical: [log]
""")

    with pytest.raises(ValueError) as exc:
        load(config_file)

    message = str(exc.value)
    assert "alta_temp" in message
    assert "default_actions" in message


def test_rejects_rule_actions_written_as_a_string(tmp_path):
    """Sem essa checagem, 'log' seria iterado letra por letra: 'l', 'o', 'g'."""
    config_file = _config_with(tmp_path, _RULE_HEAD + "      actions: log\n")

    with pytest.raises(ValueError, match="alta_temp"):
        load(config_file)


# --- resolve_threshold: onde o incidente fecha ---

def _config_with_condition(tmp_path, condition_yaml: str) -> Path:
    return _config_with(tmp_path, f"""    - name: alta_temp
      condition:
{condition_yaml}
      actions: [log]
""")


def test_resolve_threshold_is_absent_by_default(tmp_path):
    """Sem o campo, vale a margem padrão de histerese."""
    config = load(_config_with_condition(tmp_path, """        sensor_id: cpu_temp
        operator: ">"
        threshold: 80.0
"""))

    assert config.rules[0].condition.resolve_threshold is None


def test_parses_resolve_threshold(tmp_path):
    config = load(_config_with_condition(tmp_path, """        sensor_id: cpu_temp
        operator: ">"
        threshold: 80.0
        resolve_threshold: 70.0
"""))

    assert config.rules[0].condition.resolve_threshold == 70.0


def test_rejects_a_non_numeric_resolve_threshold(tmp_path):
    config_file = _config_with_condition(tmp_path, """        sensor_id: cpu_temp
        operator: ">"
        threshold: 80.0
        resolve_threshold: morno
""")

    with pytest.raises(ValueError, match="alta_temp"):
        load(config_file)


def test_rejects_a_resolve_threshold_on_the_alarm_side_of_an_upper_bound(tmp_path):
    """
    Regra '> 80' resolvendo em 85 fecharia o incidente com o sensor ainda
    acima do limite — e abriria outro na leitura seguinte.
    """
    config_file = _config_with_condition(tmp_path, """        sensor_id: cpu_temp
        operator: ">"
        threshold: 80.0
        resolve_threshold: 85.0
""")

    with pytest.raises(ValueError) as exc:
        load(config_file)

    message = str(exc.value)
    assert "alta_temp" in message
    assert "resolve_threshold" in message


def test_rejects_a_resolve_threshold_on_the_alarm_side_of_a_lower_bound(tmp_path):
    config_file = _config_with_condition(tmp_path, """        sensor_id: cpu_temp
        operator: "<"
        threshold: 20.0
        resolve_threshold: 15.0
""")

    with pytest.raises(ValueError, match="resolve_threshold"):
        load(config_file)


@pytest.mark.parametrize("operator", ["==", "anomaly"])
def test_rejects_a_resolve_threshold_without_a_numeric_edge(tmp_path, operator):
    """'==' e 'anomaly' não têm borda numérica: o campo aqui é erro de config."""
    config_file = _config_with_condition(tmp_path, f"""        sensor_id: cpu_temp
        operator: "{operator}"
        resolve_threshold: 70.0
""")

    with pytest.raises(ValueError, match="resolve_threshold"):
        load(config_file)


def test_accepts_a_resolve_threshold_equal_to_the_threshold(tmp_path):
    """Igual é permitido: significa 'sem margem', escolhido de propósito."""
    config = load(_config_with_condition(tmp_path, """        sensor_id: cpu_temp
        operator: ">"
        threshold: 80.0
        resolve_threshold: 80.0
"""))

    assert config.rules[0].condition.resolve_threshold == 80.0