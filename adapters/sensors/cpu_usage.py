import time
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
        Lê /proc/stat e calcula uso de CPU entre duas leituras.
        O Linux não expõe uso instantâneo — precisa de dois snapshots.
        """
        idle, total = self._read_stat()

        if self._prev is None:
            # primeira leitura: sem snapshot anterior, retorna 0
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
        Primeira linha de /proc/stat:
        cpu  user nice system idle iowait irq softirq steal guest guest_nice

        total = soma de todos os campos
        idle  = campo 'idle' (índice 3)
        """
        line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
        fields = [int(x) for x in line.split()[1:]]
        idle = fields[3]
        total = sum(fields)
        return idle, total