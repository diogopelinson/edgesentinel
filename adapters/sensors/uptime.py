from pathlib import Path

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading

_UPTIME_PATH = "/proc/uptime"


class UptimeSensor(BaseSensor):
    """
    Seconds since the last boot, from /proc/uptime.

    Publishes a number nobody was publishing and which makes an unexpected
    reboot detectable by a rule: `uptime < 300` fires on a device that came up
    in the last five minutes. It needed no new operator — the '<' already
    existed and simply got something to compare.

    In seconds and not in hours or days on purpose: the smaller unit is the one
    that loses no information, and the rule writes the threshold on whatever
    scale it likes.
    """

    def __init__(self, sensor_id: str = "uptime") -> None:
        super().__init__(sensor_id=sensor_id, name="Uptime", unit="seconds")

    def read(self) -> SensorReading:
        return self._build_reading(self._read_uptime())

    def _read_uptime(self) -> float:
        """
        /proc/uptime carries two fields: seconds since boot and idle seconds
        summed per CPU. Only the first one matters — the second one goes past
        the first on a machine with several cores and answers another question.

        The path is not resolved in __init__: missing hardware reports itself
        through is_available(), and that hook is unreachable if construction
        raises.
        """
        campos = Path(_UPTIME_PATH).read_text(encoding="utf-8").split()
        if not campos:
            raise RuntimeError(f"{_UPTIME_PATH} está vazio — sem uptime para ler.")

        return float(campos[0])
