from pathlib import Path

from adapters.sensors.base import BaseSensor
from core.entities import SensorReading

_LOADAVG_PATH = "/proc/loadavg"

# janela em minutos → coluna de /proc/loadavg. São as três que o kernel
# publica; não há como pedir outra
_JANELAS = {1: 0, 5: 1, 15: 2}


class LoadAverageSensor(BaseSensor):
    """
    Load average do dispositivo, de /proc/loadavg.

    Acrescenta ao motor de regras a janela temporal que o cpu_usage
    instantâneo não tem: 100% de CPU numa leitura é uma leitura, load 4
    sustentado por quinze minutos num dispositivo de um núcleo é um problema.

    A janela vem de `params.window` e vale 1, 5 ou 15 — as três que o kernel
    publica. Validada aqui, no construtor, e não no registry: o registry
    confere que `window` é um param que este sensor aceita, e só este sensor
    sabe que 7 não é uma janela que existe.
    """

    def __init__(self, sensor_id: str = "load_average", window: int = 1) -> None:
        if window not in _JANELAS:
            raise ValueError(
                f"window={window!r} não é uma janela de load average. "
                f"O kernel publica {', '.join(str(j) for j in _JANELAS)} minutos."
            )

        # a janela entra no nome porque três sensores de load no mesmo painel
        # são indistinguíveis sem ela
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
        /proc/loadavg tem cinco campos: os três load averages, a razão de
        processos rodando sobre o total e o último pid. Só os três primeiros
        interessam, e são acessados por posição a partir do começo — indexar
        do fim traria o pid.
        """
        campos = Path(_LOADAVG_PATH).read_text(encoding="utf-8").split()
        if len(campos) <= self._coluna:
            raise RuntimeError(
                f"{_LOADAVG_PATH} não tem a coluna de {self._window} minuto(s): "
                f"esperava ao menos {self._coluna + 1} campos, veio {len(campos)}."
            )

        return float(campos[self._coluna])
