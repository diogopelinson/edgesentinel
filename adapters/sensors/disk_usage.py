import os

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading


class DiskUsageSensor(BaseSensor):
    """
    Filesystem usage as a percentage, via os.statvfs().

    Covers the number one cause of failure in the field: an SD card that fills
    up. The mountpoint comes from `params.mountpoint` and defaults to '/'.

    No psutil, like the rest of the sensors — os.statvfs is in the standard
    library and brings no compiled dependency to a Raspberry Pi.
    """

    def __init__(
        self,
        sensor_id: str = "disk_usage",
        mountpoint: str = "/",
    ) -> None:
        # the mountpoint goes into the name because two disk sensors on the
        # same panel are indistinguishable without it
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
        The same arithmetic as df: used over used-plus-available, not used over
        the size of the device.

        Linux reserves a slice of the filesystem for root — on a 1 TB volume we
        measured 55 GB — and an ordinary process does not reach that slice.
        That is why the arithmetic is this one: the agent stops being able to
        write when f_bavail reaches zero, and that is where the number has to
        reach 100. Dividing by the total size would make the alert arrive after
        the disk is full, which is exactly when it is no longer any use.

        os.statvfs does not exist on Windows: the AttributeError is swallowed
        by BaseSensor's is_available(), and the sensor declares itself
        unavailable.
        """
        stat = os.statvfs(self._mountpoint)

        if stat.f_blocks == 0:
            # a pseudo-filesystem, not a disk at 0%
            raise RuntimeError(
                f"'{self._mountpoint}' informa zero blocos — "
                f"não é um sistema de arquivos com uso mensurável."
            )

        usado = stat.f_blocks - stat.f_bfree
        alcancavel = usado + stat.f_bavail

        if alcancavel == 0:
            return 100.0

        return usado / alcancavel * 100.0
