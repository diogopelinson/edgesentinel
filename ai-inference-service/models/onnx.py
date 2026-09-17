from __future__ import annotations
import logging
import numpy as np

from core.base import BaseModel, Detection

logger = logging.getLogger("ai_service.models.onnx")

SCORE_OUTPUT = "anomaly_score"


class ONNXModel(BaseModel):
    """
    Modelo de anomalia ONNX com o contrato do edgesentinel:

      entrada               : valor bruto do sensor, float32 [N, 1]
      saída 'anomaly_score' : float32 [N, 1], em [0, 1]

    A regra de score mora no artefato (scripts/train_model.py no repositório
    do edgesentinel). O serviço só lê a saída — o mesmo que o agente faz —,
    então os dois não têm como divergir.
    """

    def __init__(self, model_id: str, confidence_threshold: float = 0.6) -> None:
        super().__init__(model_id, confidence_threshold)
        self._session = None
        self._input_name: str | None = None

    def load(self, config: dict) -> None:
        import onnxruntime as ort  # type: ignore[import]

        model_path = config["path"]

        if config.get("scaler_path"):
            logger.warning(
                f"'{self.model_id}': scaler_path ignorado — a normalização "
                f"já faz parte do modelo."
            )

        session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])

        outputs = [o.name for o in session.get_outputs()]
        if SCORE_OUTPUT not in outputs:
            raise ValueError(
                f"{model_path} não tem a saída '{SCORE_OUTPUT}' "
                f"(saídas: {', '.join(outputs)}). Treine o modelo de novo com "
                f"scripts/train_model.py do edgesentinel."
            )

        self._session    = session
        self._input_name = session.get_inputs()[0].name
        self._loaded     = True
        logger.info(f"ONNX '{self.model_id}' pronto.")

    def predict(self, frame: np.ndarray) -> list[Detection]:
        """
        Para modelos ONNX de anomalia, o frame é o valor do sensor —
        um escalar ou um array cuja média é o valor.
        """
        if not self._loaded:
            raise RuntimeError(f"Modelo '{self.model_id}' não carregado.")

        value = float(np.mean(frame))
        score = self._compute_score(value)

        if score < self.confidence_threshold:
            return []

        return [Detection(
            class_name="anomaly",
            confidence=round(score, 4),
            metadata={"raw_value": value},
        )]

    def _compute_score(self, value: float) -> float:
        data = np.array([[value]], dtype=np.float32)
        (scores,) = self._session.run([SCORE_OUTPUT], {self._input_name: data})
        return float(np.clip(scores.ravel()[0], 0.0, 1.0))
