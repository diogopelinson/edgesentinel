from pathlib import Path

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading

_HWMON_ROOT = "/sys/class/hwmon"

# the names under which the kernel publishes a disk sensor: 'drivetemp' is the
# module for SATA, 'nvme' comes from the NVMe driver itself
_CHIPS_DE_DISCO = ("drivetemp", "nvme")


class DiskTemperatureSensor(BaseSensor):
    """
    Disk temperature, from /sys/class/hwmon.

    An SD card or SSD that runs hot degrades before it fails, and the
    temperature is the warning that arrives before the write error.

    On most machines this does not exist: the `drivetemp` module is not loaded
    by default and an SD card publishes no temperature at all. In that case the
    sensor declares itself unavailable, like any other one without hardware.
    """

    def __init__(
        self,
        sensor_id: str = "disk_temperature",
        chip: str | None = None,
        hwmon_root: str = _HWMON_ROOT,
    ) -> None:
        super().__init__(
            sensor_id=sensor_id,
            name="Disk Temperature",
            unit="°C",
        )
        self._chip = chip
        self._root = hwmon_root

    def read(self) -> SensorReading:
        return self._build_reading(self._read_temperature())

    def _read_temperature(self) -> float:
        """
        hwmon publishes one directory per sensor chip, each with a `name` file
        and temperatures in millidegrees.

        The name is checked before reading: hwmon exposes everything — the CPU
        package, the motherboard, the fan — and taking the first chip would
        return the temperature of something else, at a value plausible enough
        for nobody to suspect it.
        """
        procurados = (self._chip,) if self._chip else _CHIPS_DE_DISCO

        for diretorio in self._chips():
            nome = self._nome_do_chip(diretorio)
            if nome is None or nome not in procurados:
                continue

            temp = diretorio / "temp1_input"
            # not every hwmon chip publishes temp1_input; skipping is the right thing here
            if not temp.exists():
                continue

            return int(temp.read_text(encoding="utf-8").strip()) / 1000.0

        raise RuntimeError(
            f"Nenhum sensor de temperatura de disco em {self._root}. "
            f"Procurado: {', '.join(procurados)}. "
            f"Em SATA isso exige o módulo drivetemp carregado."
        )

    def _chips(self) -> list[Path]:
        """Chip directories, sorted so that the read is deterministic."""
        raiz = Path(self._root)
        if not raiz.is_dir():
            return []
        return sorted(d for d in raiz.iterdir() if d.is_dir())

    @staticmethod
    def _nome_do_chip(diretorio: Path) -> str | None:
        arquivo = diretorio / "name"
        if not arquivo.exists():
            return None
        return arquivo.read_text(encoding="utf-8").strip()
