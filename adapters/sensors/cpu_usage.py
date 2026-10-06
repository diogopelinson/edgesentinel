from pathlib import Path

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading


class CpuUsageSensor(BaseSensor):

    def __init__(self, sensor_id: str = "cpu_usage") -> None:
        super().__init__(sensor_id=sensor_id, name="CPU Usage", unit="%")
        self._prev: tuple[int, int] | None = None

    def read(self) -> SensorReading:
        return self._build_reading(self._read_usage())

    def _read_usage(self) -> float:
        """
        Reads /proc/stat and works out CPU usage between two reads.
        Linux does not expose instantaneous usage — it takes two snapshots.
        """
        idle, total = self._read_stat()

        if self._prev is None:
            # first read: no previous snapshot, returns 0
            self._prev = (idle, total)
            return 0.0

        prev_idle, prev_total = self._prev
        self._prev = (idle, total)

        diff_total = total - prev_total
        diff_idle = idle - prev_idle

        if diff_total == 0:
            return 0.0

        return (1.0 - diff_idle / diff_total) * 100.0

    def _read_stat(self) -> tuple[int, int]:
        """
        The first line of /proc/stat:
        cpu  user nice system idle iowait irq softirq steal guest guest_nice

        total = the sum of every field
        idle  = the 'idle' field (index 3)
        """
        line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
        fields = [int(x) for x in line.split()[1:]]
        idle = fields[3]
        total = sum(fields)
        return idle, total
