import threading
import time

from core.ports import StatePort


class InMemoryState(StatePort):
    """
    Process-local state — the default for a single device.

    Uses time.monotonic() for the deadlines, because a wall clock can step
    backwards on an NTP correction. A monotonic clock only means anything inside
    this process, and that is exactly why it does not appear in StatePort: the
    RedisState keeps the same state without comparing any clock at all.

    Guarded by a lock: the pipelines run on executor threads and share one
    engine, so two readings can try to take the same rule's cooldown at the same
    time.
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
