from core.ports import InferencePort
from core.entities import SensorReading, AnomalyScore

class BaseInferenceAdapter(InferencePort):
    """
    Classe base para todos os backends de inferência.
    Centraliza a construção do AnomalyScore — cada filho só
    precisa implementar _compute_score() e load().
    """

    def __init__(self, model_id: str, threshold: float = 0.7) -> None:
        self.model_id = model_id
        self.threshold = threshold

    def predict(self, reading: SensorReading) -> AnomalyScore:
        score = self._compute_score(reading)
        return AnomalyScore(
            score=round(score, 4),
            threshold=self.threshold,
            is_anomaly=score >= self.threshold,
            model_id=self.model_id,
            reading=reading,
        )

    def _compute_score(self, reading: SensorReading) -> float:
        """
        Cada backend implementa esse método.
        Retorna um float entre 0.0 e 1.0.
        """
        raise NotImplementedError