from abc import ABC, abstractmethod
from typing import Any

from core.entities import SensorReading, AnomalyScore, ActionContext


class SensorPort(ABC):
    """Contrato para qualquer fonte de dados de hardware."""

    @abstractmethod
    def read(self) -> SensorReading:
        """Lê uma medição do hardware. Deve ser não-bloqueante."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Verifica se o sensor está acessível no hardware atual."""
        ...


class InferencePort(ABC):
    """Contrato para qualquer backend de ML."""

    @abstractmethod
    def predict(self, reading: SensorReading) -> AnomalyScore:
        """Recebe uma leitura e retorna o score de anomalia."""
        ...

    @abstractmethod
    def load(self, model_path: str) -> None:
        """Carrega o modelo do disco. Separado do __init__ para lazy loading."""
        ...


class ActionPort(ABC):
    """Contrato para qualquer ação executável pelo sistema."""

    @abstractmethod
    def execute(self, context: ActionContext) -> None:
        """Executa a ação. Context carrega a leitura + score que a disparou."""
        ...


class ExporterPort(ABC):
    """Contrato para qualquer exportador de métricas."""

    @abstractmethod
    def record(self, reading: SensorReading, score: AnomalyScore | None = None) -> None:
        """Registra uma leitura para exportação."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Inicia o servidor de métricas (ex: HTTP /metrics)."""
        ...