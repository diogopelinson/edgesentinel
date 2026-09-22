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


_UPPER_BOUND = {">", ">="}
_LOWER_BOUND = {"<", "<="}

# margem de histerese: fração de |threshold| que a leitura precisa recuar
_HYSTERESIS = 0.1


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
    # ponto em que o incidente fecha; sem isso, a margem padrão
    resolve_threshold: float | None = None

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

    def resolution_point(self) -> float | None:
        """
        Valor a partir do qual o incidente fecha, ou None para operadores
        sem borda numérica ('==' e 'anomaly').

        A margem padrão é 10% de |threshold| para o lado oposto ao alarme.
        O módulo importa: com threshold -10 e operador '>', multiplicar por
        0.9 daria -9, que está do lado do alarme, e o incidente fecharia
        sozinho na leitura seguinte.
        """
        if self.operator not in _UPPER_BOUND | _LOWER_BOUND:
            return None

        if self.resolve_threshold is not None:
            return self.resolve_threshold

        margin = abs(self.threshold) * _HYSTERESIS
        return self.threshold - margin if self.operator in _UPPER_BOUND else self.threshold + margin

    def resolves(self, reading: SensorReading, score: AnomalyScore | None = None) -> bool:
        """
        True quando a leitura tira a regra do alarme com folga suficiente
        para fechar o incidente. Entre o threshold e o ponto de resolução a
        regra não dispara e o incidente também não fecha — é a faixa que
        evita abrir e fechar incidente a cada leitura.
        """
        if reading.sensor_id != self.sensor_id:
            return False

        if self.operator == "anomaly":
            # sem score não há informação: inferência fora do ar não fecha incidente
            return score is not None and not score.is_anomaly

        if self.operator == "==":
            return reading.value != self.threshold

        point = self.resolution_point()
        if point is None:
            return False

        if self.operator in _UPPER_BOUND:
            return reading.value <= point
        return reading.value >= point


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