from pathlib import Path

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading

_LOADAVG_PATH = "/proc/loadavg"

# window in minutes → column of /proc/loadavg. These are the three the kernel
# publishes; there is no way to ask for another
_JANELAS = {1: 0, 5: 1, 15: 2}


class LoadAverageSensor(BaseSensor):
    """
    The device's load average, from /proc/loadavg.

    Adds to the rule engine the time window the instantaneous cpu_usage does
    not have: 100% CPU in one read is one read, load 4 sustained for fifteen
    minutes on a single-core device is a problem.

    The window comes from `params.window` and is 1, 5 or 15 — the three the
    kernel publishes. Validated here, in the constructor, and not in the
    registry: the registry checks that `window` is a param this sensor accepts,
    and only this sensor knows that 7 is not a window that exists.
    """

    def __init__(self, sensor_id: str = "load_average", window: int = 1) -> None:
        if window not in _JANELAS:
            raise ValueError(
                f"window={window!r} não é uma janela de load average. "
                f"O kernel publica {', '.join(str(j) for j in _JANELAS)} minutos."
            )

        # the window goes into the name because three load sensors on the same
        # panel are indistinguishable without it
        super().__init__(
            sensor_id=sensor_id,
            name=f"Load Average ({window} min)",
            unit="load",
        )
        self._coluna = _JANELAS[window]
        self._window = window

    def read(self) -> SensorReading:
        return self._build_reading(self._read_loadavg())

    def _read_loadavg(self) -> float:
        """
        /proc/loadavg has five fields: the three load averages, the ratio of
        running processes over the total, and the last pid. Only the first
        three matter, and they are reached by position from the start —
        indexing from the end would bring back the pid.
        """
        campos = Path(_LOADAVG_PATH).read_text(encoding="utf-8").split()
        if len(campos) <= self._coluna:
            raise RuntimeError(
                f"{_LOADAVG_PATH} não tem a coluna de {self._window} minuto(s): "
                f"esperava ao menos {self._coluna + 1} campos, veio {len(campos)}."
            )

        return float(campos[self._coluna])
