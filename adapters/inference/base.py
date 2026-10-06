from core.ports import InferencePort
from core.entities import SensorReading, AnomalyScore

class BaseInferenceAdapter(InferencePort):
    """
    Base class for every inference backend.
    Centralizes the construction of the AnomalyScore — each child only
    needs to implement _compute_score() and load().
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
        Each backend implements this method.
        Returns a float between 0.0 and 1.0.
        """
        raise NotImplementedError
