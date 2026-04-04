from typing import Type

from adapters.sensors.base import BaseSensor
from adapters.sensors.cpu_temp import CpuTemperatureSensor
from adapters.sensors.cpu_usage import CpuUsageSensor
from adapters.sensors.memory_usage import MemoryUsageSensor


# Mapa: type do YAML → classe do sensor
_REGISTRY: dict[str, Type[BaseSensor]] = {
    "cpu_temperature": CpuTemperatureSensor,
    "cpu_usage":       CpuUsageSensor,
    "memory_usage":    MemoryUsageSensor,
}


def build_sensor(sensor_id: str, sensor_type: str) -> BaseSensor:
    """
    Recebe o id e type vindos do YAML e devolve a instância correta.

    Exemplo:
        build_sensor("cpu_temp", "cpu_temperature")
        → CpuTemperatureSensor(sensor_id="cpu_temp")
    """
    cls = _REGISTRY.get(sensor_type)
    if cls is None:
        supported = ", ".join(_REGISTRY.keys())
        raise ValueError(
            f"Tipo de sensor desconhecido: '{sensor_type}'. "
            f"Suportados: {supported}"
        )
    return cls(sensor_id=sensor_id)