from dataclasses import dataclass, field
from typing import Callable

from core.entities import SensorReading, AnomalyScore


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
    """Uma regra: quando Condition é verdadeira, executa uma lista de action_ids."""
    name: str
    condition: Condition
    action_ids: list[str]       # referência às ações registradas no container
    enabled: bool = True
    cooldown_seconds: float = 0.0   # evita spam de ação (ex: não alerta 2x em 30s)
    _last_triggered: float = field(default=0.0, init=False, repr=False)