from dataclasses import dataclass, field, replace
from enum import Enum
import time


class IncidentState(str, Enum):
    """
    The states an incident is stored in.

    NORMAL is not here: normal is the absence of an open incident. Storing it
    would mean a row for every rule that has never fired.

    Inherits from str so it crosses storage without conversion, like Severity.
    """
    TRIGGERED    = "triggered"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED     = "resolved"


@dataclass(frozen=True)
class Incident:
    """
    A rule in alarm, from its first firing until it resolves.

    It groups the firings: history events point at the incident_id instead of
    every firing becoming an incident of its own.

    Immutable like the rest of core/ — the transitions return another incident.
    """
    rule_name: str
    sensor_id: str
    severity: str
    state: IncidentState = IncidentState.TRIGGERED
    opened_at: float = field(default_factory=time.time)
    acknowledged_at: float | None = None
    resolved_at: float | None = None
    incident_id: int | None = None      # assigned by the store on open

    @property
    def is_open(self) -> bool:
        """Acknowledged still counts as open: someone saw it, the problem goes on."""
        return self.state is not IncidentState.RESOLVED

    def acknowledge(self, at: float) -> "Incident":
        return replace(self, state=IncidentState.ACKNOWLEDGED, acknowledged_at=at)

    def resolve(self, at: float) -> "Incident":
        return replace(self, state=IncidentState.RESOLVED, resolved_at=at)
