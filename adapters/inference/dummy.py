from adapters.inference.base import BaseInferenceAdapter
from core.entities import SensorReading


class DummyInferenceAdapter(BaseInferenceAdapter):
    """
    Backend de desenvolvimento — não carrega nenhum modelo.
    Sempre retorna score 0.0 (tudo normal).

    Útil para:
    - rodar o sistema sem ter um modelo treinado
    - testes automatizados que não devem depender de ML
    - validar que o pipeline completo funciona antes de integrar ML real
    """

    def __init__(self, threshold: float = 0.7) -> None:
        super().__init__(model_id="dummy", threshold=threshold)

    def load(self, model_path: str) -> None:
        # Dummy não carrega nada — aceita o chamado mas ignora
        pass

    def _compute_score(self, reading: SensorReading) -> float:
        return 0.0