from __future__ import annotations
import logging
import numpy as np

from core.base import BaseModel, Detection

logger = logging.getLogger("ai_service.models.onnx")


class ONNXModel(BaseModel):
    """
    Wrapper ONNX — suporta qualquer modelo exportado para ONNX.
    Especificamente calibrado para o IsolationForest do edgesentinel.
    """

    def __init__(self, model_id: str, confidence_threshold: float = 0.6) -> None:
        super().__init__(model_id, confidence_threshold)
        self._model_session  = None
        self._scaler_session = None
        self._score_min: float = 0.0
        self._score_max: float = 1.0

    def load(self, config: dict) -> None:
        import onnxruntime as ort  # type: ignore[import]
        from pathlib import Path

        model_path  = config["path"]
        scaler_path = config.get("scaler_path")

        self._model_session = ort.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
        )

        if scaler_path and Path(scaler_path).exists():
            self._scaler_session = ort.InferenceSession(
                scaler_path,
                providers=["CPUExecutionProvider"],
            )

        self._calibrate()
        self._loaded = True
        logger.info(f"ONNX '{self.model_id}' pronto.")

    def predict(self, frame: np.ndarray) -> list[Detection]:
        """
        Para modelos ONNX de anomalia, o frame pode ser um array 1D
        com o valor do sensor em metadata — ou um valor escalar.
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
        input_data = np.array([[value]], dtype=np.float32)

        if self._scaler_session:
            name   = self._scaler_session.get_inputs()[0].name
            scaled = self._scaler_session.run(None, {name: input_data})[0]
        else:
            scaled = input_data

        name   = self._model_session.get_inputs()[0].name
        output = self._model_session.run(None, {name: scaled})
        raw    = float(np.array(output[1]).flatten()[0])

        span = self._score_max - self._score_min
        if span == 0:
            return 0.0

        normalized = (raw - self._score_min) / span
        return float(max(0.0, min(1.0, 1.0 - normalized)))

    def _calibrate(self) -> None:
        normal_vals  = [50.0, 55.0, 60.0, 65.0]
        anomaly_vals = [85.0, 90.0, 95.0]

        scores = [self._raw_score(v) for v in normal_vals + anomaly_vals]
        self._score_min = min(scores)
        self._score_max = max(scores)

    def _raw_score(self, value: float) -> float:
        input_data = np.array([[value]], dtype=np.float32)
        if self._scaler_session:
            name   = self._scaler_session.get_inputs()[0].name
            scaled = self._scaler_session.run(None, {name: input_data})[0]
        else:
            scaled = input_data
        name   = self._model_session.get_inputs()[0].name
        output = self._model_session.run(None, {name: scaled})
        return float(np.array(output[1]).flatten()[0])