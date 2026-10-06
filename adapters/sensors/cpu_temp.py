import re
from pathlib import Path

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading


# The standard paths where Linux exposes CPU temperature
_THERMAL_PATHS = [
    "/sys/class/thermal/thermal_zone0/temp",
    "/sys/class/thermal/thermal_zone1/temp",
]

# The Raspberry Pi specific path (via vcgencmd)
_VCGENCMD_PATH = "/usr/bin/vcgencmd"


class CpuTemperatureSensor(BaseSensor):

    def __init__(self, sensor_id: str = "cpu_temp") -> None:
        super().__init__(sensor_id=sensor_id, name="CPU Temperature", unit="°C")

    def read(self) -> SensorReading:
        path = self._find_thermal_path()
        if path == "vcgencmd":
            return self._build_reading(self._read_vcgencmd())
        return self._build_reading(self._read_sysfs(path))

    # --- private methods ---

    def _find_thermal_path(self) -> str:
        """
        Picks the best source available on the hardware at hand.

        Resolved per read, not in __init__: a sensor signals missing hardware
        through is_available(), and that hook is unreachable if construction
        raises.
        """
        for path in _THERMAL_PATHS:
            if Path(path).exists():
                return path
        if Path(_VCGENCMD_PATH).exists():
            return "vcgencmd"

        tentados = ", ".join([*_THERMAL_PATHS, _VCGENCMD_PATH])
        raise RuntimeError(
            f"Nenhuma fonte de temperatura de CPU encontrada. "
            f"Caminhos tentados: {tentados}"
        )

    def _read_sysfs(self, path: str) -> float:
        """
        /sys/class/thermal/thermal_zone0/temp returns the value in millidegrees.
        E.g. "72500" → 72.5°C
        """
        raw = Path(path).read_text(encoding="utf-8").strip()
        return int(raw) / 1000.0

    def _read_vcgencmd(self) -> float:
        """
        vcgencmd measure_temp returns "temp=72.5'C".
        Only the number has to be extracted from it.
        """
        import subprocess
        result = subprocess.run(
            [_VCGENCMD_PATH, "measure_temp"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        match = re.search(r"temp=([\d.]+)", result.stdout)
        if not match:
            raise RuntimeError(f"Saída inesperada do vcgencmd: {result.stdout!r}")
        return float(match.group(1))
