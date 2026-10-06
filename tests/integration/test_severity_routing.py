"""
default_actions end to end: YAML → loader → mapper → RuleEngine.

Real actions would be log and webhook; here they are ActionPort mocks, because
the question is which actions the engine dispatches, not what each one does.
"""
from unittest.mock import MagicMock

import pytest

from application.engine import RuleEngine
from config.loader import load
from config.mapper import to_rules
from core.entities import SensorReading
from core.ports import ActionPort


CONFIG = """
edgesentinel:
  sensors:
    - id: cpu_temp
      type: cpu_temperature

  default_actions:
    warning:  [log]
    critical: [log, webhook, buzzer]

  rules:
    - name: alta_temperatura
      condition: {sensor_id: cpu_temp, operator: ">", threshold: 75.0}
      severity: warning

    - name: temperatura_critica
      condition: {sensor_id: cpu_temp, operator: ">", threshold: 85.0}
      severity: critical

    - name: registro_apenas
      condition: {sensor_id: cpu_temp, operator: ">", threshold: 70.0}
      severity: critical
      actions: []

  actions:
    - {id: log, type: log}
"""


@pytest.fixture
def dispatch(tmp_path):
    """Evaluates a reading and returns {action_id: number of calls}."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(CONFIG, encoding="utf-8")
    rules = to_rules(load(config_file))

    def run(value: float) -> dict[str, int]:
        actions = {name: MagicMock(spec=ActionPort) for name in ("log", "webhook", "buzzer")}
        RuleEngine(rules=rules, actions=actions).evaluate(
            SensorReading("cpu_temp", "CPU Temperature", value, "°C")
        )
        return {name: a.execute.call_count for name, a in actions.items()}

    return run


def test_warning_level_dispatches_the_warning_defaults(dispatch):
    # 78 °C: matches alta_temperatura (warning) and registro_apenas (no actions)
    assert dispatch(78.0) == {"log": 1, "webhook": 0, "buzzer": 0}


def test_critical_level_adds_the_critical_defaults(dispatch):
    # 90 °C: warning → log; critical → log, webhook, buzzer; registro_apenas → nothing
    assert dispatch(90.0) == {"log": 2, "webhook": 1, "buzzer": 1}


def test_rule_with_explicit_empty_actions_dispatches_nothing(dispatch):
    # 72 °C: only registro_apenas matches, and it declared actions: []
    assert dispatch(72.0) == {"log": 0, "webhook": 0, "buzzer": 0}
