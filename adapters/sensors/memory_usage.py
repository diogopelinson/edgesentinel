from pathlib import Path

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading


class MemoryUsageSensor(BaseSensor):

    def __init__(self, sensor_id: str = "memory_usage") -> None:
        super().__init__(sensor_id=sensor_id, name="Memory Usage", unit="%")

    def read(self) -> SensorReading:
        return self._build_reading(self._read_meminfo())

    def _read_meminfo(self) -> float:
        """
        /proc/meminfo expõe várias linhas. As que importam:
            MemTotal:    total de RAM
            MemAvailable: RAM disponível (mais preciso que MemFree)

        uso = (1 - disponível / total) * 100
        """
        data: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts[0] in ("MemTotal:", "MemAvailable:"):
                data[parts[0]] = int(parts[1])  # valor em kB

        total = data["MemTotal:"]
        available = data["MemAvailable:"]

        return (1.0 - available / total) * 100.0