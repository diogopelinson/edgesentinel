import logging

from config.schema import EdgeSentinelConfig
from config.mapper import to_rules
from adapters.sensors.registry import build_sensor
from adapters.inference.registry import build_inference
from adapters.actions.registry import build_actions
from adapters.exporter.prometheus import PrometheusExporter
from application.engine import RuleEngine
from application.pipeline import Pipeline
from application.monitor import MonitorLoop

logger = logging.getLogger("edgesentinel.builder")


def build_monitor(config: EdgeSentinelConfig) -> MonitorLoop:
    sensors  = _build_sensors(config)
    cameras  = _build_cameras(config)
    inference = _build_inference(config)
    yolo     = _build_yolo(config)
    actions  = build_actions(config.actions)
    rules    = to_rules(config)
    exporter = PrometheusExporter(port=config.exporter.port)

    engine = RuleEngine(rules=rules, actions=actions)

    sensor_pipelines = [
            Pipeline(sensor=s, engine=engine, inference=inference, exporter=exporter)
            for s in sensors
        ]

    camera_pipelines = [
        Pipeline(sensor=c, engine=engine, inference=yolo, exporter=exporter)
        for c in cameras
    ] if yolo else []

    all_pipelines = sensor_pipelines + camera_pipelines

    if not all_pipelines:
        raise RuntimeError(
            "Nenhum pipeline disponível — "
            "verifique sensores, câmeras e o config.yaml."
        )

    return MonitorLoop(
        pipelines=all_pipelines,
        poll_interval_seconds=config.poll_interval_seconds,
        exporter=exporter,
    )


def _build_sensors(config: EdgeSentinelConfig):
    sensors = []
    for sensor_config in config.sensors:
        try:
            sensor = build_sensor(sensor_config.id, sensor_config.type)
            if not sensor.is_available():
                logger.warning(
                    f"Sensor '{sensor_config.id}' ({sensor_config.type}) "
                    f"não disponível nesse hardware — ignorando."
                )
                continue
            sensors.append(sensor)
            logger.info(f"Sensor '{sensor_config.id}' registrado.")
        except Exception as e:
            logger.error(f"Falha ao construir sensor '{sensor_config.id}': {e}")

    if not sensors:
        # só lança erro se também não houver câmeras configuradas
        if not config.cameras:
            raise RuntimeError(
                "Nenhum sensor disponível. Verifique o hardware e o config.yaml."
            )
        logger.warning(
            "Nenhum sensor de hardware disponível — "
            "sistema rodará apenas com câmeras."
        )

    return sensors


def _build_cameras(config: EdgeSentinelConfig):
    cameras = []
    for cam_config in config.cameras:
        try:
            if cam_config.simulated:
                from adapters.sensors.camera_simulated import SimulatedCameraSensor
                sensor = SimulatedCameraSensor(
                    sensor_id=cam_config.sensor_id,
                    name=cam_config.name,
                    mode=cam_config.simulated_mode,
                )
            else:
                from adapters.sensors.camera import CameraSensor
                sensor = CameraSensor(
                    sensor_id=cam_config.sensor_id,
                    source=cam_config.source,
                    name=cam_config.name,
                    fps_limit=cam_config.fps_limit,
                )
            cameras.append(sensor)
            logger.info(f"Câmera '{cam_config.sensor_id}' registrada.")
        except Exception as e:
            logger.error(f"Falha ao construir câmera '{cam_config.sensor_id}': {e}")
    return cameras


def _build_inference(config: EdgeSentinelConfig):
    if not config.inference.enabled:
        logger.info("Inferência desabilitada no config.")
        return None

    try:
        adapter = build_inference(
            backend=config.inference.backend,
            model_path=config.inference.model_path,
        )
        logger.info(f"Backend de inferência '{config.inference.backend}' carregado.")
        return adapter
    except Exception as e:
        logger.error(f"Falha ao carregar inferência: {e}. Continuando sem ML.")
        return None


def _build_yolo(config: EdgeSentinelConfig):
    if not config.yolo.enabled:
        logger.info("YOLO desabilitado no config.")
        return None

    try:
        from adapters.inference.yolo import YOLOInferenceAdapter
        adapter = YOLOInferenceAdapter(
            threshold=config.yolo.confidence,
            target_classes=config.yolo.target_classes,
        )
        adapter.load(config.yolo.model_path)
        classes = config.yolo.target_classes or ["todas"]
        logger.info(f"YOLO carregado. Classes alvo: {classes}")
        return adapter
    except Exception as e:
        logger.error(f"Falha ao carregar YOLO: {e}. Continuando sem câmera.")
        return None