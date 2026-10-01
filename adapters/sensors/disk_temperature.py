from pathlib import Path

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading

_HWMON_ROOT = "/sys/class/hwmon"

# nomes com que o kernel publica um sensor de disco: 'drivetemp' é o módulo
# para SATA, 'nvme' vem do próprio driver NVMe
_CHIPS_DE_DISCO = ("drivetemp", "nvme")


class DiskTemperatureSensor(BaseSensor):
    """
    Temperatura do disco, de /sys/class/hwmon.

    Um cartão SD ou SSD que esquenta degrada antes de falhar, e a temperatura é
    o aviso que chega antes do erro de escrita.

    Na maioria das máquinas isto não existe: o módulo `drivetemp` não vem
    carregado por padrão e um cartão SD não publica temperatura nenhuma. Nesse
    caso o sensor se declara indisponível, como qualquer outro sem hardware.
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
        hwmon publica um diretório por chip de sensor, cada um com um arquivo
        `name` e temperaturas em milligraus.

        O nome é conferido antes de ler: hwmon expõe de tudo — pacote da CPU,
        placa-mãe, ventoinha — e pegar o primeiro chip devolveria a temperatura
        de outra coisa, num valor plausível o bastante para ninguém desconfiar.
        """
        procurados = (self._chip,) if self._chip else _CHIPS_DE_DISCO

        for diretorio in self._chips():
            nome = self._nome_do_chip(diretorio)
            if nome is None or nome not in procurados:
                continue

            temp = diretorio / "temp1_input"
            # nem todo chip hwmon publica temp1_input; pular é o certo aqui
            if not temp.exists():
                continue

            return int(temp.read_text(encoding="utf-8").strip()) / 1000.0

        raise RuntimeError(
            f"Nenhum sensor de temperatura de disco em {self._root}. "
            f"Procurado: {', '.join(procurados)}. "
            f"Em SATA isso exige o módulo drivetemp carregado."
        )

    def _chips(self) -> list[Path]:
        """Diretórios de chip, ordenados para a leitura ser determinística."""
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
