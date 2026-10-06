from adapters.inference.base import BaseInferenceAdapter
from core.entities import SensorReading


class DummyInferenceAdapter(BaseInferenceAdapter):
    """
    Development backend — loads no model at all.
    Always returns score 0.0 (everything normal).

    Useful for:
    - running the system without having a trained model
    - automated tests that must not depend on ML
    - checking that the full pipeline works before integrating real ML
    """

    def __init__(self, threshold: float = 0.7) -> None:
        super().__init__(model_id="dummy", threshold=threshold)

    def load(self, model_path: str) -> None:
        # Dummy loads nothing — it accepts the call but ignores it
        pass

    def _compute_score(self, reading: SensorReading) -> float:
        return 0.0
