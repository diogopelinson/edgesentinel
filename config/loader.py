from pathlib import Path
import yaml

from config.schema import (
    EdgeSentinelConfig,
    SensorConfig,
    InferenceConfig,
    ExporterConfig,
    RuleConfig,
    ConditionConfig,
    ActionConfig,
    CameraConfig,
    YOLOConfig,
)


def load(path: str | Path) -> EdgeSentinelConfig:
    raw = _read_yaml(path)
    return _parse(raw)


def _read_yaml(path: str | Path) -> dict:
    resolved = Path(path).resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {resolved}")

    with resolved.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "edgesentinel" not in data:
        raise ValueError("YAML inválido: precisa ter uma chave raiz 'edgesentinel'")

    return data["edgesentinel"]


def _parse(raw: dict) -> EdgeSentinelConfig:
    return EdgeSentinelConfig(
        poll_interval_seconds=raw.get("poll_interval_seconds", 5.0),
        sensors=_parse_sensors(raw.get("sensors", [])),
        inference=_parse_inference(raw.get("inference", {})),
        exporter=_parse_exporter(raw.get("exporter", {})),
        rules=_parse_rules(raw.get("rules", [])),
        actions=_parse_actions(raw.get("actions", [])),
        cameras=_parse_cameras(raw.get("cameras", [])),
        yolo=_parse_yolo(raw.get("yolo", {})),
    )


def _parse_sensors(raw: list[dict]) -> list[SensorConfig]:
    result = []
    for item in raw:
        if "id" not in item or "type" not in item:
            raise ValueError(f"Sensor inválido — precisa de 'id' e 'type': {item}")
        result.append(SensorConfig(id=item["id"], type=item["type"]))
    return result


def _parse_inference(raw: dict) -> InferenceConfig:
    return InferenceConfig(
        enabled=raw.get("enabled", False),
        backend=raw.get("backend", "dummy"),
        model_path=raw.get("model_path"),
        service_url=raw.get("service_url", "http://localhost:8080"),
        model_id=raw.get("model_id"),     
    )


def _parse_exporter(raw: dict) -> ExporterConfig:
    return ExporterConfig(
        port=raw.get("port", 8000),
        backend=raw.get("backend", "prometheus"),
        endpoint=raw.get("endpoint", "http://localhost:4317"),
        service_name=raw.get("service_name", "edgesentinel"),
        use_otel=raw.get("use_otel", False),
    )


def _parse_rules(raw: list[dict]) -> list[RuleConfig]:
    result = []
    for item in raw:
        if "name" not in item or "condition" not in item:
            raise ValueError(f"Regra inválida — precisa de 'name' e 'condition': {item}")

        cond_raw  = item["condition"]
        condition = ConditionConfig(
            sensor_id=cond_raw["sensor_id"],
            operator=cond_raw["operator"],
            threshold=float(cond_raw.get("threshold", 0.0)),
        )

        result.append(RuleConfig(
            name=item["name"],
            condition=condition,
            actions=item.get("actions", []),
            cooldown_seconds=float(item.get("cooldown_seconds", 0.0)),
            enabled=item.get("enabled", True),
        ))
    return result


def _parse_actions(raw: list[dict]) -> list[ActionConfig]:
    result = []
    for item in raw:
        if "id" not in item or "type" not in item:
            raise ValueError(f"Action inválida — precisa de 'id' e 'type': {item}")
        result.append(ActionConfig(
            id=item["id"],
            type=item["type"],
            url=item.get("url"),
        ))
    return result


def _parse_cameras(raw: list[dict]) -> list[CameraConfig]:
    result = []
    for item in raw:
        if "sensor_id" not in item or "source" not in item:
            raise ValueError(f"Camera inválida — precisa de 'sensor_id' e 'source': {item}")
        result.append(CameraConfig(
            sensor_id=item["sensor_id"],
            source=item["source"],
            name=item.get("name", "Camera"),
            fps_limit=float(item.get("fps_limit", 1.0)),
            simulated=item.get("simulated", False),
            simulated_mode=item.get("simulated_mode", "noise"),
        ))
    return result


def _parse_yolo(raw: dict) -> YOLOConfig:
    return YOLOConfig(
        enabled=raw.get("enabled", False),
        model_path=raw.get("model_path", "models/yolov8n.pt"),
        target_classes=raw.get("target_classes", []),
        confidence=float(raw.get("confidence", 0.5)),
    )