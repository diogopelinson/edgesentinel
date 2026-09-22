from dataclasses import dataclass
from enum import Enum
from typing import Callable

from core.entities import SensorReading, AnomalyScore


class Severity(str, Enum):
    """
    Peso de uma regra quando ela dispara.

    Herda de str para atravessar ActionContext.extras — e, mais adiante, a
    serialização do Event Store — sem conversão em cada fronteira.
    """
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"

    @classmethod
    def from_name(cls, name: str) -> "Severity":
        """Converte o texto do YAML. Case-insensitive porque é escrito à mão."""
        try:
            return cls(name.strip().lower())
        except ValueError:
            aceitos = ", ".join(s.value for s in cls)
            raise ValueError(
                f"Severidade desconhecida: '{name}'. Aceitos: {aceitos}"
            ) from None


@dataclass
class Condition:
    """
    Condição avaliável contra uma leitura.
    
    Exemplo via YAML:
        when: "cpu_temp > 75"
    
    Exemplo via código:
        Condition(sensor_id="cpu_temp", operator=">", threshold=75.0)
    """
    sensor_id: str
    operator: str       # ">", "<", ">=", "<=", "==", "anomaly"
    threshold: float = 0.0

    def evaluate(self, reading: SensorReading, score: AnomalyScore | None = None) -> bool:
        if reading.sensor_id != self.sensor_id:
            return False

        if self.operator == "anomaly":
            return score is not None and score.is_anomaly

        ops: dict[str, Callable[[float, float], bool]] = {
            ">":  lambda v, t: v > t,
            "<":  lambda v, t: v < t,
            ">=": lambda v, t: v >= t,
            "<=": lambda v, t: v <= t,
            "==": lambda v, t: v == t,
        }

        op_fn = ops.get(self.operator)
        if op_fn is None:
            raise ValueError(f"Operador desconhecido: {self.operator}")

        return op_fn(reading.value, self.threshold)


@dataclass
class Rule:
    """
    Uma regra: quando Condition é verdadeira, executa uma lista de action_ids.

    Só declaração — o estado do cooldown mora no StatePort, com o engine.
    """
    name: str
    condition: Condition
    action_ids: list[str]       # referência às ações registradas no container
    severity: Severity = Severity.WARNING
    enabled: bool = True
    cooldown_seconds: float = 0.0   # evita spam de ação (ex: não alerta 2x em 30s)