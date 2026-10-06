import pytest
from pathlib import Path

from config.loader import load


def test_loads_valid_config(tmp_path):
    """tmp_path is a pytest built-in fixture — it creates a temporary folder."""
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
    """A minimal config must use the default values."""
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
    """No existing config declares severity — they must all stay valid."""
    config = load(_config_with_rule_severity(tmp_path, ""))

    assert config.rules[0].severity == "warning"


def test_severity_is_case_insensitive(tmp_path):
    config = load(_config_with_rule_severity(tmp_path, "      severity: CRITICAL"))

    assert config.rules[0].severity == "critical"


def test_raises_on_unknown_severity(tmp_path):
    """
    An invalid severity has to fail at load time, not on the rule's first
    firing — which may happen days later, in the field.
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
    """History with no configuration at all — the database is born on the first run."""
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
    Zero retention would wipe the whole history on every start-up — it is
    almost certainly a typo, not an intention.
    """
    config_file = _config_with_event_store(tmp_path, f"""
  event_store:
    retention_days: {retention}
""")

    with pytest.raises(ValueError, match="retention_days"):
        load(config_file)


# --- default_actions and the actions field of the rules ---

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
    """None, not an empty list: it is what lets the mapper apply default_actions."""
    config = load(_config_with(tmp_path, _RULE_HEAD))

    assert config.rules[0].actions is None


def test_explicit_empty_actions_are_kept_as_empty(tmp_path):
    """`actions: []` is a choice — record in the history only — and must not become 'use the default'."""
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
    """'warning' and 'Warning' become the same key — one of the two would be silently discarded."""
    config_file = _config_with(tmp_path, _RULE_HEAD, """
  default_actions:
    warning: [log]
    Warning: [webhook]
""")

    with pytest.raises(ValueError, match="warning"):
        load(config_file)


def test_rejects_rule_actions_written_as_a_severity_map(tmp_path):
    """
    A rule has a single severity — a per-severity map inside it makes no
    sense. The error has to point at where that map does belong.
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
    """Without this check, 'log' would be iterated letter by letter: 'l', 'o', 'g'."""
    config_file = _config_with(tmp_path, _RULE_HEAD + "      actions: log\n")

    with pytest.raises(ValueError, match="alta_temp"):
        load(config_file)


# --- resolve_threshold: where the incident closes ---

def _config_with_condition(tmp_path, condition_yaml: str) -> Path:
    return _config_with(tmp_path, f"""    - name: alta_temp
      condition:
{condition_yaml}
      actions: [log]
""")


def test_resolve_threshold_is_absent_by_default(tmp_path):
    """Without the field, the default hysteresis margin applies."""
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
    A '> 80' rule resolving at 85 would close the incident with the sensor
    still above the limit — and open another on the next reading.
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
    """'==' and 'anomaly' have no numeric edge: the field here is a config error."""
    config_file = _config_with_condition(tmp_path, f"""        sensor_id: cpu_temp
        operator: "{operator}"
        resolve_threshold: 70.0
""")

    with pytest.raises(ValueError, match="resolve_threshold"):
        load(config_file)


def test_accepts_a_resolve_threshold_equal_to_the_threshold(tmp_path):
    """Equal is allowed: it means 'no margin', chosen on purpose."""
    config = load(_config_with_condition(tmp_path, """        sensor_id: cpu_temp
        operator: ">"
        threshold: 80.0
        resolve_threshold: 80.0
"""))

    assert config.rules[0].condition.resolve_threshold == 80.0


# --- per-sensor params ---

CONFIG_COM_PARAMS = """
edgesentinel:
  sensors:
    - id: disco
      type: cpu_usage
      params:
        mountpoint: /var
        limite: 90
        fator: 0.5
        ativo: true
    - id: simples
      type: cpu_usage
  rules:
    - name: r
      condition:
        sensor_id: disco
        operator: ">"
        threshold: 1.0
      actions: [log]
  actions:
    - id: log
      type: log
"""


def escreve(tmp_path, texto):
    arquivo = tmp_path / "config.yaml"
    arquivo.write_text(texto, encoding="utf-8")
    return arquivo


class TestSensorParams:
    """
    The params block is free-form on purpose: the schema cannot know every
    sensor type up front, or every new sensor goes through config/schema.py.
    """

    def test_params_are_parsed(self, tmp_path):
        config = load(escreve(tmp_path, CONFIG_COM_PARAMS))

        disco = config.sensors[0]
        assert disco.params["mountpoint"] == "/var"

    def test_the_yaml_types_are_preserved(self, tmp_path):
        """
        The YAML already distinguishes int, float, bool and str. The loader
        must not normalize to string: a sensor expecting a pin receives 17, not
        "17".
        """
        disco = load(escreve(tmp_path, CONFIG_COM_PARAMS)).sensors[0]

        assert disco.params["limite"] == 90
        assert isinstance(disco.params["limite"], int)
        assert disco.params["fator"] == 0.5
        assert isinstance(disco.params["fator"], float)
        assert disco.params["ativo"] is True
        assert isinstance(disco.params["mountpoint"], str)

    def test_a_sensor_without_params_gets_an_empty_dict(self, tmp_path):
        """
        Never None: the consumer does **params and a None there would be a TypeError.
        """
        simples = load(escreve(tmp_path, CONFIG_COM_PARAMS)).sensors[1]

        assert simples.params == {}

    def test_an_explicit_null_is_an_empty_dict_too(self, tmp_path):
        texto = CONFIG_COM_PARAMS.replace(
            "      params:\n        mountpoint: /var\n        limite: 90\n"
            "        fator: 0.5\n        ativo: true\n",
            "      params:\n",
        )

        assert load(escreve(tmp_path, texto)).sensors[0].params == {}

    def test_nested_structures_pass_through(self, tmp_path):
        texto = CONFIG_COM_PARAMS.replace(
            "        ativo: true\n",
            "        ativo: true\n        faixas: [1, 2, 3]\n"
            "        limites:\n          alto: 9\n",
        )

        params = load(escreve(tmp_path, texto)).sensors[0].params
        assert params["faixas"] == [1, 2, 3]
        assert params["limites"] == {"alto": 9}

    def test_params_that_is_not_a_mapping_is_refused_naming_the_sensor(self, tmp_path):
        """
        `params: 5` would blow up later at the ** with a TypeError that does
        not say which sensor in the YAML is wrong.
        """
        texto = CONFIG_COM_PARAMS.replace(
            "      params:\n        mountpoint: /var\n        limite: 90\n"
            "        fator: 0.5\n        ativo: true\n",
            "      params: 5\n",
        )

        with pytest.raises(ValueError) as erro:
            load(escreve(tmp_path, texto))

        assert "disco" in str(erro.value)
        assert "params" in str(erro.value)
