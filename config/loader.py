from pathlib import Path
import yaml

from core.rules import Severity, LOWER_BOUND, UPPER_BOUND
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
    EventStoreConfig,
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
        event_store=_parse_event_store(raw.get("event_store", {})),
        default_actions=_parse_default_actions(raw.get("default_actions")),
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
            resolve_threshold=_parse_resolve_threshold(cond_raw, rule_name=item["name"]),
        )

        result.append(RuleConfig(
            name=item["name"],
            condition=condition,
            actions=_parse_rule_actions(item.get("actions"), rule_name=item["name"]),
            severity=_parse_severity(item, rule_name=item["name"]),
            cooldown_seconds=float(item.get("cooldown_seconds", 0.0)),
            enabled=item.get("enabled", True),
        ))
    return result


def _parse_resolve_threshold(cond_raw: dict, rule_name: str) -> float | None:
    """
    Valida o ponto em que o incidente fecha. Um valor do lado do alarme
    fecharia o incidente com o sensor ainda fora do limite, e a leitura
    seguinte abriria outro — o oposto do que a histerese existe para fazer.
    """
    if "resolve_threshold" not in cond_raw:
        return None

    raw      = cond_raw["resolve_threshold"]
    operator = cond_raw.get("operator")

    try:
        resolve_threshold = float(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"Regra '{rule_name}': resolve_threshold precisa ser um número, "
            f"recebido: {raw!r}"
        ) from None

    if operator not in UPPER_BOUND | LOWER_BOUND:
        raise ValueError(
            f"Regra '{rule_name}': resolve_threshold não se aplica ao operador "
            f"'{operator}', que não tem borda numérica."
        )

    threshold = float(cond_raw.get("threshold", 0.0))
    if operator in UPPER_BOUND and resolve_threshold > threshold:
        raise ValueError(
            f"Regra '{rule_name}': resolve_threshold ({resolve_threshold:g}) precisa "
            f"ser menor ou igual ao threshold ({threshold:g}) para o operador "
            f"'{operator}' — acima dele o incidente fecharia ainda em alarme."
        )
    if operator in LOWER_BOUND and resolve_threshold < threshold:
        raise ValueError(
            f"Regra '{rule_name}': resolve_threshold ({resolve_threshold:g}) precisa "
            f"ser maior ou igual ao threshold ({threshold:g}) para o operador "
            f"'{operator}' — abaixo dele o incidente fecharia ainda em alarme."
        )

    return resolve_threshold


def _parse_severity(item: dict, rule_name: str) -> str:
    """
    Valida a severidade no carregamento, não no primeiro disparo da regra —
    uma regra pode ficar sem casar por dias antes de disparar pela primeira
    vez, e até lá o erro de digitação já foi para campo.
    """
    raw = item.get("severity", Severity.WARNING.value)
    try:
        return Severity.from_name(str(raw)).value
    except ValueError as e:
        raise ValueError(f"Regra '{rule_name}': {e}") from None


def _parse_rule_actions(raw, rule_name: str) -> list[str] | None:
    """
    None quando a regra não declara `actions` — o mapper aplica
    default_actions. Uma lista vazia declarada continua vazia.
    """
    if raw is None:
        return None

    if isinstance(raw, dict):
        raise ValueError(
            f"Regra '{rule_name}': 'actions' precisa ser uma lista de ids. "
            f"Uma regra tem uma severidade só — ações por severidade vão no "
            f"bloco 'default_actions', no nível do edgesentinel."
        )

    if not _is_list_of_ids(raw):
        raise ValueError(
            f"Regra '{rule_name}': 'actions' precisa ser uma lista de ids, "
            f"recebido: {raw!r}"
        )

    return list(raw)


def _parse_default_actions(raw) -> dict[str, list[str]]:
    if raw is None:
        return {}

    if not isinstance(raw, dict):
        raise ValueError(
            "default_actions precisa ser um mapa severidade → lista de ids, "
            "por exemplo  critical: [log, webhook]"
        )

    result: dict[str, list[str]] = {}
    for key, ids in raw.items():
        try:
            severity = Severity.from_name(str(key)).value
        except ValueError as e:
            raise ValueError(f"default_actions: {e}") from None

        # 'warning' e 'Warning' viram a mesma chave — uma das listas sumiria
        if severity in result:
            raise ValueError(
                f"default_actions: a severidade '{severity}' aparece mais de uma vez"
            )

        if not _is_list_of_ids(ids):
            raise ValueError(
                f"default_actions.{key} precisa ser uma lista de ids, recebido: {ids!r}"
            )

        result[severity] = list(ids)

    return result


def _is_list_of_ids(value) -> bool:
    return isinstance(value, list) and all(isinstance(i, str) for i in value)


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


def _parse_event_store(raw: dict) -> EventStoreConfig:
    defaults  = EventStoreConfig()
    retention = float(raw.get("retention_days", defaults.retention_days))

    # o start() do store poda tudo fora da janela — retenção zero apagaria
    # o histórico inteiro a cada inicialização
    if retention <= 0:
        raise ValueError(
            f"event_store.retention_days precisa ser maior que zero, "
            f"recebido: {retention:g}"
        )

    return EventStoreConfig(
        enabled=bool(raw.get("enabled", defaults.enabled)),
        path=str(raw.get("path", defaults.path)),
        retention_days=retention,
    )


def _parse_yolo(raw: dict) -> YOLOConfig:
    return YOLOConfig(
        enabled=raw.get("enabled", False),
        model_path=raw.get("model_path", "models/yolov8n.pt"),
        target_classes=raw.get("target_classes", []),
        confidence=float(raw.get("confidence", 0.5)),
    )
