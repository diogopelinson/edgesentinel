from dataclasses import dataclass
from enum import Enum
from collections.abc import Callable

from core.entities import SensorReading, AnomalyScore


class Severity(str, Enum):
    """
    How much a rule weighs when it fires.

    Inherits from str so it crosses ActionContext.extras — and, further on, the
    Event Store's serialization — without a conversion at every boundary.
    """
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"

    @classmethod
    def from_name(cls, name: str) -> "Severity":
        """Convert the text from the YAML. Case-insensitive, because it is hand-written."""
        try:
            return cls(name.strip().lower())
        except ValueError:
            aceitos = ", ".join(s.value for s in cls)
            raise ValueError(
                f"Severidade desconhecida: '{name}'. Aceitos: {aceitos}"
            ) from None


UPPER_BOUND = {">", ">="}
LOWER_BOUND = {"<", "<="}

# hysteresis margin: the fraction of |threshold| a reading has to come back by
_HYSTERESIS = 0.1


@dataclass
class Condition:
    """
    A condition that can be evaluated against a reading.

    From YAML:
        when: "cpu_temp > 75"

    From code:
        Condition(sensor_id="cpu_temp", operator=">", threshold=75.0)
    """
    sensor_id: str
    operator: str       # ">", "<", ">=", "<=", "==", "anomaly"
    threshold: float = 0.0
    # where the incident closes; without it, the default margin applies
    resolve_threshold: float | None = None

    def evaluate(self, reading: SensorReading, score: AnomalyScore | None = None) -> bool:
        if reading.sensor_id != self.sensor_id:
            return False

        if self.operator == "anomaly":
            return score is not None and score.is_anomaly

        ops: dict[str, Callable[[float, float], bool]] = {
            ">":  lambda v, t: v > t,
            "<":  lambda v, t: v < t,
            ">=": lambda v, t: v >= t,
            "<=": lambda v, t: v <= t,
            "==": lambda v, t: v == t,
        }

        op_fn = ops.get(self.operator)
        if op_fn is None:
            raise ValueError(f"Operador desconhecido: {self.operator}")

        return op_fn(reading.value, self.threshold)

    def resolution_point(self) -> float | None:
        """
        The value at which the incident closes, or None for the operators with
        no numeric edge ('==' and 'anomaly').

        The default margin is 10% of |threshold|, moved away from the alarm.
        The absolute value matters: with a threshold of -10 and operator '>',
        multiplying by 0.9 would give -9, which is on the alarm side, and the
        incident would close itself on the very next reading.
        """
        if self.operator not in UPPER_BOUND | LOWER_BOUND:
            return None

        if self.resolve_threshold is not None:
            return self.resolve_threshold

        margin = abs(self.threshold) * _HYSTERESIS
        return self.threshold - margin if self.operator in UPPER_BOUND else self.threshold + margin

    def resolves(self, reading: SensorReading, score: AnomalyScore | None = None) -> bool:
        """
        True when the reading takes the rule out of alarm by enough to close
        the incident. Between the threshold and the resolution point the rule
        does not fire and the incident does not close either — that band is
        what stops an incident opening and closing on every reading.
        """
        if reading.sensor_id != self.sensor_id:
            return False

        if self.operator == "anomaly":
            # no score is no information: inference being down does not close an incident
            return score is not None and not score.is_anomaly

        if self.operator == "==":
            return reading.value != self.threshold

        point = self.resolution_point()
        if point is None:
            return False

        if self.operator in UPPER_BOUND:
            return reading.value <= point
        return reading.value >= point


@dataclass
class Rule:
    """
    A rule: when its Condition holds, run a list of action_ids.

    Declaration only — the cooldown state lives in the StatePort, with the
    engine.
    """
    name: str
    condition: Condition
    action_ids: list[str]       # references the actions registered in the container
    severity: Severity = Severity.WARNING
    enabled: bool = True
    cooldown_seconds: float = 0.0   # stops action spam (e.g. no second alert within 30s)
