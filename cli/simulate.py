import time
import logging
import argparse

from config.loader import load
from config.mapper import to_rules
from adapters.sensors.simulated import SimulatedSensor
from adapters.inference.dummy import DummyInferenceAdapter
from adapters.actions.registry import build_actions
from adapters.exporter.prometheus import PrometheusExporter
from application.engine import RuleEngine
from application.pipeline import Pipeline

logger = logging.getLogger("edgesentinel.simulate")


SCENARIOS = {
    "normal": {
        "description": "Operação normal — valores estáveis dentro do esperado",
        "sensors": [
            SimulatedSensor("cpu_temp",     "CPU Temperature", "°C",  base_value=55.0, amplitude=4.0,  scenario="normal"),
            SimulatedSensor("cpu_usage",    "CPU Usage",       "%",   base_value=30.0, amplitude=10.0, scenario="normal"),
            SimulatedSensor("memory_usage", "Memory Usage",    "%",   base_value=45.0, amplitude=5.0,  scenario="normal"),
        ]
    },
    "stress": {
        "description": "Stress — temperatura sobe progressivamente e dispara alertas",
        "sensors": [
            SimulatedSensor("cpu_temp",     "CPU Temperature", "°C",  base_value=60.0, amplitude=3.0,  scenario="stress"),
            SimulatedSensor("cpu_usage",    "CPU Usage",       "%",   base_value=70.0, amplitude=8.0,  scenario="stress"),
            SimulatedSensor("memory_usage", "Memory Usage",    "%",   base_value=60.0, amplitude=4.0,  scenario="normal"),
        ]
    },
    "spike": {
        "description": "Spike — picos repentinos de temperatura a cada ~20 segundos",
        "sensors": [
            SimulatedSensor("cpu_temp",     "CPU Temperature", "°C",  base_value=55.0, amplitude=3.0,  scenario="spike"),
            SimulatedSensor("cpu_usage",    "CPU Usage",       "%",   base_value=40.0, amplitude=5.0,  scenario="normal"),
            SimulatedSensor("memory_usage", "Memory Usage",    "%",   base_value=50.0, amplitude=5.0,  scenario="normal"),
        ]
    },
}


def run_simulate(scenario: str, config_path: str, interval: float) -> None:
    if scenario not in SCENARIOS:
        print(f"Cenário desconhecido: '{scenario}'. Disponíveis: {', '.join(SCENARIOS)}")
        return

    s = SCENARIOS[scenario]
    print(f"\nedgesentinel simulate")
    print(f"Cenário : {scenario} — {s['description']}")
    print(f"Intervalo: {interval}s")
    print(f"Métricas : http://localhost:8000/metrics")
    print(f"\nPressione Ctrl+C para parar.\n")
    print("-" * 60)

    # carrega config e monta peças reais
    config   = load(config_path)
    rules    = to_rules(config)
    actions  = build_actions(config.actions)
    inference = DummyInferenceAdapter()
    exporter  = PrometheusExporter(port=config.exporter.port)
    exporter.start()

    engine = RuleEngine(rules=rules, actions=actions)
    pipelines = [
        Pipeline(sensor=sensor, engine=engine, inference=inference, exporter=exporter)
        for sensor in s["sensors"]
    ]

    try:
        tick = 0
        while True:
            tick += 1
            print(f"\n[tick {tick:03d}]")

            for pipeline in pipelines:
                # lê o sensor e imprime o valor no terminal
                reading = pipeline._sensor.read()
                print(f"  {reading.name:<20} {reading.value:>7.2f} {reading.unit}")

                # roda o pipeline real (inferência + regras + ações)
                pipeline.run_once()

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\nSimulação encerrada.")