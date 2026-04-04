import re
from pathlib import Path

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading


# Caminhos padrão onde o Linux expõe temperatura de CPU
_THERMAL_PATHS = [
    "/sys/class/thermal/thermal_zone0/temp",
    "/sys/class/thermal/thermal_zone1/temp",
]

# Caminho específico do Raspberry Pi (via vcgencmd)
_VCGENCMD_PATH = "/usr/bin/vcgencmd"


class CpuTemperatureSensor(BaseSensor):

    def __init__(self, sensor_id: str = "cpu_temp") -> None:
        super().__init__(sensor_id=sensor_id, name="CPU Temperature", unit="°C")
        self._path = self._find_thermal_path()

    def read(self) -> SensorReading:
        if self._path == "vcgencmd":
            return self._build_reading(self._read_vcgencmd())
        return self._build_reading(self._read_sysfs())

    # --- métodos privados ---

    def _find_thermal_path(self) -> str:
        """Escolhe a melhor fonte disponível no hardware atual."""
        for path in _THERMAL_PATHS:
            if Path(path).exists():
                return path
        if Path(_VCGENCMD_PATH).exists():
            return "vcgencmd"
        raise RuntimeError("Nenhuma fonte de temperatura encontrada nesse hardware.")

    def _read_sysfs(self) -> float:
        """
        /sys/class/thermal/thermal_zone0/temp retorna o valor em milligraus.
        Ex: "72500" → 72.5°C
        """
        raw = Path(self._path).read_text(encoding="utf-8").strip()
        return int(raw) / 1000.0

    def _read_vcgencmd(self) -> float:
        """
        vcgencmd measure_temp retorna "temp=72.5'C".
        Precisamos extrair só o número.
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