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


@dataclass
class ConditionConfig:
    sensor_id: str
    operator: str
    threshold: float = 0.0


@dataclass
class ActionConfig:
    id: str
    type: str
    url: str | None = None      # usado pelo webhook


@dataclass
class RuleConfig:
    name: str
    condition: ConditionConfig
    actions: list[str]
    cooldown_seconds: float = 0.0
    enabled: bool = True


@dataclass
class EdgeSentinelConfig:
    sensors: list[SensorConfig]
    rules: list[RuleConfig]
    actions: list[ActionConfig]
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    exporter: ExporterConfig = field(default_factory=ExporterConfig)
    poll_interval_seconds: float = 5.0