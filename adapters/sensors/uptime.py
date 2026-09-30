from pathlib import Path

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading

_UPTIME_PATH = "/proc/uptime"


class UptimeSensor(BaseSensor):
    """
    Segundos desde o último boot, de /proc/uptime.

    Publica um número que ninguém estava publicando e que torna um reboot
    inesperado detectável por regra: `uptime < 300` dispara num dispositivo
    que subiu nos últimos cinco minutos. Não precisou de operador novo — o
    '<' já existia e passou a ter o que comparar.

    Em segundos e não em horas ou dias de propósito: a unidade menor é a que
    não perde informação, e a regra escreve o limiar na escala que quiser.
    """

    def __init__(self, sensor_id: str = "uptime") -> None:
        super().__init__(sensor_id=sensor_id, name="Uptime", unit="seconds")

    def read(self) -> SensorReading:
        return self._build_reading(self._read_uptime())

    def _read_uptime(self) -> float:
        """
        /proc/uptime traz dois campos: segundos desde o boot e segundos
        ociosos somados por CPU. Só o primeiro interessa — o segundo passa do
        primeiro numa máquina com vários núcleos e responde outra pergunta.

        O caminho não é resolvido no __init__: ausência de hardware se informa
        por is_available(), e esse hook fica inalcançável se a construção
        levantar exceção.
        """
        campos = Path(_UPTIME_PATH).read_text(encoding="utf-8").split()
        if not campos:
            raise RuntimeError(f"{_UPTIME_PATH} está vazio — sem uptime para ler.")

        return float(campos[0])
