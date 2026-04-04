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