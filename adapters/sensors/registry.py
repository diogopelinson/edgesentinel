
import inspect
from typing import Any

from adapters.sensors.base import BaseSensor
from adapters.sensors.cpu_temp import CpuTemperatureSensor
from adapters.sensors.cpu_usage import CpuUsageSensor
from adapters.sensors.disk_temperature import DiskTemperatureSensor
from adapters.sensors.disk_usage import DiskUsageSensor
from adapters.sensors.load_average import LoadAverageSensor
from adapters.sensors.memory_usage import MemoryUsageSensor
from adapters.sensors.uptime import UptimeSensor


# Map: type from the YAML → sensor class
_REGISTRY: dict[str, type[BaseSensor]] = {
    "cpu_temperature": CpuTemperatureSensor,
    "cpu_usage":       CpuUsageSensor,
    "memory_usage":    MemoryUsageSensor,
    "uptime":          UptimeSensor,
    "load_average":    LoadAverageSensor,
    "disk_usage":       DiskUsageSensor,
    "disk_temperature": DiskTemperatureSensor,
}


def build_sensor(
    sensor_id: str,
    sensor_type: str,
    params: dict[str, Any] | None = None,
) -> BaseSensor:
    """
    Takes the id, the type and the params coming from the YAML and returns the
    instance.

    For example:
        build_sensor("cpu_temp", "cpu_temperature")
        → CpuTemperatureSensor(sensor_id="cpu_temp")

        build_sensor("estufa", "bme280", {"bus": 1, "address": 0x76})
        → Bme280Sensor(sensor_id="estufa", bus=1, address=118)

    What each sensor accepts is the signature of its own __init__ — there is no
    second list to keep in sync.
    """
    cls = _REGISTRY.get(sensor_type)
    if cls is None:
        supported = ", ".join(_REGISTRY.keys())
        raise ValueError(
            f"Tipo de sensor desconhecido: '{sensor_type}'. "
            f"Suportados: {supported}"
        )

    params = params or {}
    _check_params(cls, sensor_id, sensor_type, params)
    return cls(sensor_id=sensor_id, **params)


def _check_params(
    cls: type[BaseSensor],
    sensor_id: str,
    sensor_type: str,
    params: dict[str, Any],
) -> None:
    """
    Checks the params against the signature **before** constructing.

    Calling and catching TypeError would be shorter and would lump together two
    different errors: 'this sensor does not accept this param', which is
    config, and 'the sensor's constructor broke', which is a bug — and it would
    send the operator to edit a YAML that was right. On top of that, a sensor
    that takes a pin or opens a bus in __init__ would already have done it by
    the time the error showed up.
    """
    if "sensor_id" in params:
        raise ValueError(
            f"Sensor '{sensor_id}': 'sensor_id' não vai em params — "
            f"o id do sensor é o campo 'id' do YAML."
        )

    assinatura = inspect.signature(cls.__init__)
    parametros = assinatura.parameters.values()

    # **kwargs in the signature is the sensor saying it accepts any param, which
    # is how a generic I2C or SPI adapter declares itself
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parametros):
        return

    aceitos = {
        p.name for p in parametros
        if p.name not in ("self", "sensor_id")
        and p.kind is not inspect.Parameter.VAR_POSITIONAL
    }

    # all of them at once: one per boot round would make the operator find the
    # errors one at a time, and each round is a deploy on the device
    desconhecidos = sorted(set(params) - aceitos)
    if desconhecidos:
        raise ValueError(
            f"Sensor '{sensor_id}' (type '{sensor_type}') não aceita "
            f"{_lista(desconhecidos)} em params. "
            f"Aceita: {', '.join(sorted(aceitos)) or '(nenhum param)'}."
        )


def _lista(nomes: list[str]) -> str:
    """'a' for one, \'a\', \'b\' for several — the message reads better that way."""
    return ", ".join(f"'{n}'" for n in nomes)
