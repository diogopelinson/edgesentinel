import os

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading


class DiskUsageSensor(BaseSensor):
    """
    Uso do sistema de arquivos em percentual, via os.statvfs().

    Cobre a causa número um de falha em campo: cartão SD que enche. O
    mountpoint vem de `params.mountpoint` e o default é '/'.

    Sem psutil, como o resto dos sensores — os.statvfs é da biblioteca padrão
    e não traz dependência compilada para um Raspberry Pi.
    """

    def __init__(
        self,
        sensor_id: str = "disk_usage",
        mountpoint: str = "/",
    ) -> None:
        # o mountpoint entra no nome porque dois sensores de disco no mesmo
        # painel são indistinguíveis sem ele
        super().__init__(
            sensor_id=sensor_id,
            name=f"Disk Usage ({mountpoint})",
            unit="%",
        )
        self._mountpoint = mountpoint

    def read(self) -> SensorReading:
        return self._build_reading(self._read_usage())

    def _read_usage(self) -> float:
        """
        A mesma conta do df: usado sobre usado-mais-disponível, não usado sobre
        o tamanho do dispositivo.

        O Linux reserva uma fatia do sistema de arquivos para o root — num
        volume de 1 TB medimos 55 GB — e um processo comum não alcança essa
        fatia. É por isso que a conta é essa: o agente para de conseguir
        escrever quando f_bavail chega a zero, e é ali que o número precisa
        chegar a 100. Dividir pelo tamanho total faria o alerta chegar depois
        do disco cheio, que é exatamente quando ele não serve mais.

        os.statvfs não existe no Windows: o AttributeError é engolido pelo
        is_available() do BaseSensor, e o sensor se declara indisponível.
        """
        stat = os.statvfs(self._mountpoint)

        if stat.f_blocks == 0:
            # pseudo-sistema de arquivos, não um disco em 0%
            raise RuntimeError(
                f"'{self._mountpoint}' informa zero blocos — "
                f"não é um sistema de arquivos com uso mensurável."
            )

        usado = stat.f_blocks - stat.f_bfree
        alcancavel = usado + stat.f_bavail

        if alcancavel == 0:
            return 100.0

        return usado / alcancavel * 100.0
