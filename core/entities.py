from dataclasses import dataclass, field
from typing import Any
import time


@dataclass(frozen=True)
class SensorReading:
    """One immutable sensor reading. frozen=True means nobody edits it after creation."""
    sensor_id: str
    name: str
    value: float
    unit: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnomalyScore:
    """An anomaly score produced by an InferencePort."""
    score: float          # 0.0 = normal, 1.0 = fully anomalous
    threshold: float      # the configured firing threshold
    is_anomaly: bool      # score >= threshold
    model_id: str         # which model produced this score
    reading: SensorReading


@dataclass(frozen=True)
class Event:
    """
    The stored record of a rule that fired.

    severity is a str, not a Severity: core/rules.py imports this module, and
    the value arrives here already as the plain text that goes to storage.
    """
    rule_name: str
    sensor_id: str
    value: float
    unit: str
    severity: str
    timestamp: float = field(default_factory=time.time)
    anomaly_score: float | None = None
    event_id: int | None = None       # assigned by the store on write
    incident_id: int | None = None    # the incident this firing belongs to


@dataclass
class ActionContext:
    """What an ActionPort receives when a rule fires."""
    rule_name: str
    reading: SensorReading
    score: AnomalyScore | None = None
    extras: dict[str, Any] = field(default_factory=dict)
