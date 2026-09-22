import threading
import time

from core.ports import StatePort


class InMemoryState(StatePort):
    """
    Estado local do processo — o padrão de um dispositivo só.

    Usa time.monotonic() para os prazos, porque o relógio de parede pode
    andar para trás num ajuste de NTP. O monotônico só vale dentro deste
    processo, e é exatamente por isso que ele não aparece no StatePort: o
    RedisState guarda o mesmo estado sem comparar relógio nenhum.

    Protegido por lock: os pipelines rodam em threads do executor e
    compartilham o mesmo engine, então duas leituras podem tentar tomar o
    cooldown da mesma regra ao mesmo tempo.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expires_at: dict[str, float] = {}
        self._values: dict[str, str] = {}

    def try_acquire(self, key: str, ttl_seconds: float) -> bool:
        if ttl_seconds <= 0:
            return True

        now = time.monotonic()
        with self._lock:
            expires_at = self._expires_at.get(key)
            if expires_at is not None and expires_at > now:
                return False
            self._expires_at[key] = now + ttl_seconds
            return True

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._values[key] = value
