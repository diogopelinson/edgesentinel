from abc import ABC, abstractmethod
from typing import Any

from core.entities import SensorReading, AnomalyScore, ActionContext, Event


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


class EventPort(ABC):
    """Contrato para qualquer armazenamento do histórico de regras disparadas."""

    @abstractmethod
    def start(self) -> None:
        """Abre o armazenamento. Construir não pode tocar o disco."""
        ...

    @abstractmethod
    def append(self, event: Event) -> None:
        """Registra um evento. Não pode bloquear quem chama."""
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
        """Eventos mais recentes primeiro. since e until são inclusivos."""
        ...

    @abstractmethod
    def prune(self, before: float) -> int:
        """Remove eventos anteriores a before e devolve quantos saíram."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Grava o que ainda estiver pendente e libera o armazenamento."""
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