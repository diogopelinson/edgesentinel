from abc import ABC, abstractmethod

from core.entities import SensorReading, AnomalyScore, ActionContext, Event
from core.incidents import Incident


class SensorPort(ABC):
    """The contract for any source of hardware data."""

    @abstractmethod
    def read(self) -> SensorReading:
        """Take one measurement from the hardware. Must not block."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Whether the sensor can be reached on this machine."""
        ...


class InferencePort(ABC):
    """The contract for any ML backend."""

    @abstractmethod
    def predict(self, reading: SensorReading) -> AnomalyScore:
        """Take a reading and return its anomaly score."""
        ...

    @abstractmethod
    def load(self, model_path: str) -> None:
        """Load the model from disk. Separate from __init__ for lazy loading."""
        ...


class ActionPort(ABC):
    """The contract for anything the system can execute as an action."""

    @abstractmethod
    def execute(self, context: ActionContext) -> None:
        """Run the action. The context carries the reading and score that fired it."""
        ...


class StatePort(ABC):
    """
    The contract for state that outlives a single evaluation — rule cooldowns
    today, and more of the incident cycle later.

    No method exposes a timestamp: a monotonic clock's epoch is per process and
    means nothing in another one. Whoever takes a key decides how long for, and
    the implementation is what expires it — in memory, with its own monotonic
    clock; in Redis, with server-side expiry.
    """

    @abstractmethod
    def try_acquire(self, key: str, ttl_seconds: float) -> bool:
        """
        Take the key for ttl_seconds. True if it was free just now, False until
        the previous hold expires. ttl_seconds <= 0 always takes it.

        Has to be atomic: two simultaneous callers cannot both take the same
        key.
        """
        ...

    @abstractmethod
    def get(self, key: str) -> str | None:
        """The stored value, or None if the key was never written."""
        ...

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        """Store a value under the key, with no expiry."""
        ...


class EventPort(ABC):
    """The contract for any store of the rule-firing history."""

    @abstractmethod
    def start(self) -> None:
        """Open the store. Constructing must not touch the disk."""
        ...

    @abstractmethod
    def append(self, event: Event) -> None:
        """Record an event. Must not block the caller."""
        ...

    @abstractmethod
    def query(
        self,
        *,
        severity: str | None = None,
        sensor_id: str | None = None,
        rule_name: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Newest events first. since and until are inclusive."""
        ...

    @abstractmethod
    def prune(self, before: float) -> int:
        """Delete events older than before, and return how many went."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Write whatever is still pending and release the store."""
        ...


class IncidentPort(ABC):
    """
    The contract for the incident lifecycle.

    Unlike StatePort, this state has to be durable and queryable: an operator
    lists what is open, acknowledges one of them from another process (the
    CLI), and the agent has to see that on its next cycle.
    """

    @abstractmethod
    def open_incident(self, incident: Incident) -> Incident:
        """
        Open an incident and return it with the incident_id assigned.

        A rule has at most one open incident — that is what makes the firings
        group together instead of each becoming an incident.
        """
        ...

    @abstractmethod
    def acknowledge_incident(self, incident_id: int, at: float) -> None:
        """Mark it acknowledged without closing: someone saw it, the problem goes on."""
        ...

    @abstractmethod
    def resolve_incident(self, incident_id: int, at: float) -> None:
        """Close the incident."""
        ...

    @abstractmethod
    def open_incidents(self) -> list[Incident]:
        """The incidents still open, oldest first."""
        ...


class IncidentMetricsPort(ABC):
    """
    The contract for counting incident lifecycle transitions.

    Separate from ExporterPort on purpose: that one records a reading, this one
    an episode. The engine gets this port and not the other — it has no reading
    to export, only the transition it just made.

    There is no method for "how many are open right now". That number is
    current state and comes from the incident store at collection time, because
    the engine holds no incident in memory and a per-process counter would be
    wrong after a restart.

    Every implementation is observation, never alarm: the caller swallows the
    failure.
    """

    @abstractmethod
    def record_incident_opened(self, incident: Incident) -> None:
        """Count an episode opening — once per incident, not once per firing."""
        ...

    @abstractmethod
    def record_incident_resolved(
        self, incident: Incident, duration_seconds: float,
    ) -> None:
        """
        Count the close and record how long it lasted.

        The duration is passed in because the incident handed over is the one
        that was open: whoever closes it is who knows the timestamp of the
        reading that closed it.
        """
        ...


class ExporterPort(ABC):
    """The contract for any metrics exporter."""

    @abstractmethod
    def record(self, reading: SensorReading, score: AnomalyScore | None = None) -> None:
        """Record a reading for export."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Start the metrics server (for example, HTTP /metrics)."""
        ...
