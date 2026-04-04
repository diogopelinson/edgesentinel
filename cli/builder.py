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
    """
    Recebe o config carregado e devolve um MonitorLoop pronto pra rodar.
    Toda a lógica de montagem fica aqui — o main.py só chama essa função.
    """
    sensors   = _build_sensors(config)
    inference = _build_inference(config)
    actions   = build_actions(config.actions)
    rules     = to_rules(config)
    exporter  = PrometheusExporter(port=config.exporter.port)

    engine = RuleEngine(rules=rules, actions=actions)

    pipelines = [
        Pipeline(
            sensor=sensor,
            engine=engine,
            inference=inference,
            exporter=exporter,
        )
        for sensor in sensors
    ]

    return MonitorLoop(
        pipelines=pipelines,
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
        raise RuntimeError(
            "Nenhum sensor disponível. Verifique o hardware e o config.yaml."
        )

    return sensors


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