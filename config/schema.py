from dataclasses import dataclass, field
from typing import Any


@dataclass
class SensorConfig:
    id: str
    type: str
    # Deliberately free: the schema does not know every sensor type, or every
    # new sensor would have to come through here. What validates it is the
    # class signature, in build_sensor(). Never None — the consumer does **params.
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class InferenceConfig:
    enabled: bool = False
    backend: str = "dummy"
    model_path: str | None = None
    service_url: str = "http://localhost:8080"
    model_id: str | None = None


@dataclass
class ExporterConfig:
    port: int = 8000
    backend: str = "prometheus"
    endpoint: str = "http://localhost:4317"
    service_name: str = "edgesentinel"
    use_otel: bool = False


@dataclass
class ConditionConfig:
    sensor_id: str
    operator: str
    threshold: float = 0.0
    # where the incident closes; None uses the default hysteresis margin
    resolve_threshold: float | None = None


@dataclass
class ActionConfig:
    id: str
    type: str
    url: str | None = None


@dataclass
class RuleConfig:
    name: str
    condition: ConditionConfig
    # None = undeclared, uses default_actions; [] = no action, history only
    actions: list[str] | None = None
    severity: str = "warning"
    cooldown_seconds: float = 0.0
    enabled: bool = True


@dataclass
class CameraConfig:
    sensor_id: str
    source: str
    name: str = "Camera"
    fps_limit: float = 1.0
    simulated: bool = False
    simulated_mode: str = "noise"


@dataclass
class YOLOConfig:
    enabled: bool = False
    model_path: str = "models/yolov8n.pt"
    target_classes: list[str] = field(default_factory=list)
    confidence: float = 0.5


@dataclass
class EventStoreConfig:
    enabled: bool = True
    path: str = "data/events.db"
    retention_days: float = 30.0


@dataclass
class EdgeSentinelConfig:
    sensors: list[SensorConfig]
    rules: list[RuleConfig]
    actions: list[ActionConfig]
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    exporter: ExporterConfig = field(default_factory=ExporterConfig)
    poll_interval_seconds: float = 5.0
    cameras: list[CameraConfig] = field(default_factory=list)
    yolo: YOLOConfig = field(default_factory=YOLOConfig)
    event_store: EventStoreConfig = field(default_factory=EventStoreConfig)
    # severity → actions, for rules that declare no `actions`
    default_actions: dict[str, list[str]] = field(default_factory=dict)
