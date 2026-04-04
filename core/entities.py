from dataclasses import dataclass, field
from typing import Any
import time


@dataclass(frozen=True)
class SensorReading:
    """Leitura imutável de um sensor. frozen=True garante que ninguém altera após criação."""
    sensor_id: str
    name: str
    value: float
    unit: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnomalyScore:
    """Score de anomalia produzido por um InferencePort."""
    score: float          # 0.0 = normal, 1.0 = anomalia total
    threshold: float      # limiar configurado para disparo
    is_anomaly: bool      # score >= threshold
    model_id: str         # qual modelo gerou esse score
    reading: SensorReading


@dataclass
class ActionContext:
    """Contexto passado para um ActionPort quando uma regra dispara."""
    rule_name: str
    reading: SensorReading
    score: AnomalyScore | None = None
    extras: dict[str, Any] = field(default_factory=dict)