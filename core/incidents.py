from dataclasses import dataclass, field, replace
from enum import Enum
import time


class IncidentState(str, Enum):
    """
    Estados guardados de um incidente.

    NORMAL não aparece aqui: o normal é a ausência de incidente aberto.
    Guardá-lo significaria uma linha por regra que nunca disparou.

    Herda de str para atravessar o armazenamento sem conversão, como
    Severity.
    """
    TRIGGERED    = "triggered"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED     = "resolved"


@dataclass(frozen=True)
class Incident:
    """
    Uma regra em alarme, do primeiro disparo até a resolução.

    Agrupa os disparos: os eventos do histórico apontam para o incident_id,
    em vez de cada disparo virar um incidente novo.

    Imutável como as demais entidades do core — as transições devolvem
    outro incidente.
    """
    rule_name: str
    sensor_id: str
    severity: str
    state: IncidentState = IncidentState.TRIGGERED
    opened_at: float = field(default_factory=time.time)
    acknowledged_at: float | None = None
    resolved_at: float | None = None
    incident_id: int | None = None      # atribuído pelo store ao abrir

    @property
    def is_open(self) -> bool:
        """Reconhecido ainda é aberto: alguém viu, mas o problema continua."""
        return self.state is not IncidentState.RESOLVED

    def acknowledge(self, at: float) -> "Incident":
        return replace(self, state=IncidentState.ACKNOWLEDGED, acknowledged_at=at)

    def resolve(self, at: float) -> "Incident":
        return replace(self, state=IncidentState.RESOLVED, resolved_at=at)
