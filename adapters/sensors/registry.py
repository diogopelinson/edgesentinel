
import inspect
from typing import Any

from adapters.sensors.base import BaseSensor
from adapters.sensors.cpu_temp import CpuTemperatureSensor
from adapters.sensors.cpu_usage import CpuUsageSensor
from adapters.sensors.memory_usage import MemoryUsageSensor
from adapters.sensors.uptime import UptimeSensor


# Mapa: type do YAML → classe do sensor
_REGISTRY: dict[str, type[BaseSensor]] = {
    "cpu_temperature": CpuTemperatureSensor,
    "cpu_usage":       CpuUsageSensor,
    "memory_usage":    MemoryUsageSensor,
    "uptime":          UptimeSensor,
}


def build_sensor(
    sensor_id: str,
    sensor_type: str,
    params: dict[str, Any] | None = None,
) -> BaseSensor:
    """
    Recebe o id, o type e os params vindos do YAML e devolve a instância.

    Exemplo:
        build_sensor("cpu_temp", "cpu_temperature")
        → CpuTemperatureSensor(sensor_id="cpu_temp")

        build_sensor("estufa", "bme280", {"bus": 1, "address": 0x76})
        → Bme280Sensor(sensor_id="estufa", bus=1, address=118)

    O que cada sensor aceita é a assinatura do seu __init__ — não há segunda
    lista para manter em sincronia.
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
    Confere os params contra a assinatura **antes** de construir.

    Chamar e capturar TypeError seria mais curto e juntaria dois erros
    diferentes: 'esse sensor não aceita esse param', que é config, e 'o
    construtor do sensor quebrou', que é bug — e mandaria o operador editar um
    YAML que estava certo. Além disso um sensor que toma um pino ou abre um
    barramento no __init__ já teria feito isso quando o erro aparecesse.
    """
    if "sensor_id" in params:
        raise ValueError(
            f"Sensor '{sensor_id}': 'sensor_id' não vai em params — "
            f"o id do sensor é o campo 'id' do YAML."
        )

    assinatura = inspect.signature(cls.__init__)
    parametros = assinatura.parameters.values()

    # **kwargs na assinatura é o sensor dizendo que aceita qualquer param, que
    # é como um adapter I2C ou SPI genérico se declara
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parametros):
        return

    aceitos = {
        p.name for p in parametros
        if p.name not in ("self", "sensor_id")
        and p.kind is not inspect.Parameter.VAR_POSITIONAL
    }

    # todos de uma vez: um por rodada de boot faria o operador descobrir os
    # erros de um em um, e cada rodada é um deploy no dispositivo
    desconhecidos = sorted(set(params) - aceitos)
    if desconhecidos:
        raise ValueError(
            f"Sensor '{sensor_id}' (type '{sensor_type}') não aceita "
            f"{_lista(desconhecidos)} em params. "
            f"Aceita: {', '.join(sorted(aceitos)) or '(nenhum param)'}."
        )


def _lista(nomes: list[str]) -> str:
    """'a' para um, \'a\', \'b\' para vários — a mensagem lê melhor assim."""
    return ", ".join(f"'{n}'" for n in nomes)
