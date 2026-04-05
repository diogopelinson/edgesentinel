from dataclasses import dataclass, field


@dataclass
class SensorConfig:
    id: str
    type: str


@dataclass
class InferenceConfig:
    enabled: bool = False
    backend: str = "dummy"
    model_path: str | None = None


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


@dataclass
class ActionConfig:
    id: str
    type: str
    url: str | None = None


@dataclass
class RuleConfig:
    name: str
    condition: ConditionConfig
    actions: list[str]
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
class EdgeSentinelConfig:
    sensors: list[SensorConfig]
    rules: list[RuleConfig]
    actions: list[ActionConfig]
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    exporter: ExporterConfig = field(default_factory=ExporterConfig)
    poll_interval_seconds: float = 5.0
    cameras: list[CameraConfig] = field(default_factory=list)
    yolo: YOLOConfig = field(default_factory=YOLOConfig)