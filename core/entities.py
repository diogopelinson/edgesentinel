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


@dataclass(frozen=True)
class Event:
    """
    Registro persistido de uma regra que disparou.

    severity é str, não Severity: core/rules.py importa este módulo, e o
    valor já chega aqui como o texto puro que vai para o armazenamento.
    """
    rule_name: str
    sensor_id: str
    value: float
    unit: str
    severity: str
    timestamp: float = field(default_factory=time.time)
    anomaly_score: float | None = None
    event_id: int | None = None       # atribuído pelo store ao persistir
    incident_id: int | None = None    # incidente que agrupa este disparo


@dataclass
class ActionContext:
    """Contexto passado para um ActionPort quando uma regra dispara."""
    rule_name: str
    reading: SensorReading
    score: AnomalyScore | None = None
    extras: dict[str, Any] = field(default_factory=dict)
