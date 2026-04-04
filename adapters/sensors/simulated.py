import math
import time
import random
from adapters.sensors.base import BaseSensor
from core.entities import SensorReading


class SimulatedSensor(BaseSensor):
    """
    Sensor que gera dados falsos mas realistas.
    Usa uma função senoidal + ruído para simular variação natural.
    Suporta cenários: normal, stress, spike.
    """

    def __init__(
        self,
        sensor_id: str,
        name: str,
        unit: str,
        base_value: float,
        amplitude: float = 5.0,
        scenario: str = "normal",
    ) -> None:
        super().__init__(sensor_id=sensor_id, name=name, unit=unit)
        self.base_value = base_value
        self.amplitude = amplitude
        self.scenario = scenario
        self._start = time.monotonic()

    def read(self) -> SensorReading:
        return self._build_reading(self._generate())

    def is_available(self) -> bool:
        return True  # simulado sempre está disponível

    def _generate(self) -> float:
        elapsed = time.monotonic() - self._start

        # onda senoidal suave — simula variação natural
        wave = math.sin(elapsed * 0.3) * self.amplitude

        # ruído pequeno — simula imprecisão do sensor
        noise = random.uniform(-1.0, 1.0)

        value = self.base_value + wave + noise

        # aplica cenário
        if self.scenario == "stress":
            # valor sobe progressivamente ao longo do tempo
            ramp = min(elapsed * 0.5, 30.0)
            value += ramp

        elif self.scenario == "spike":
            # pico aleatório a cada ~20s
            if int(elapsed) % 20 < 3:
                value += 25.0
        value = max(0.0, min(100.0, value))
        return round(value, 2)