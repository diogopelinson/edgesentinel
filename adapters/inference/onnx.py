from __future__ import annotations
from pathlib import Path
import numpy as np

from adapters.inference.base import BaseInferenceAdapter
from core.entities import SensorReading


class ONNXInferenceAdapter(BaseInferenceAdapter):
    """
    Backend ONNX Runtime com pipeline scaler + IsolationForest.

    Espera dois arquivos na mesma pasta:
      - anomaly.onnx  → modelo IsolationForest
      - scaler.onnx   → MinMaxScaler para normalização
    """

    def __init__(self, threshold: float = 0.6) -> None:
        super().__init__(model_id="onnx", threshold=threshold)
        self._model_session  = None
        self._scaler_session = None
        self._score_min: float | None = None
        self._score_max: float | None = None

    def load(self, model_path: str) -> None:
        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError("Execute: pip install onnxruntime")

        model_p  = Path(model_path)
        scaler_p = model_p.parent / "scaler.onnx"

        if not model_p.exists():
            raise FileNotFoundError(f"Modelo não encontrado: {model_p}")
        if not scaler_p.exists():
            raise FileNotFoundError(f"Scaler não encontrado: {scaler_p}")

        self._model_session  = ort.InferenceSession(str(model_p),  providers=["CPUExecutionProvider"])
        self._scaler_session = ort.InferenceSession(str(scaler_p), providers=["CPUExecutionProvider"])

        # calibra o range de scores com valores de referência
        self._calibrate()

    def _calibrate(self) -> None:
        """
        Roda inferência em valores de referência para descobrir
        o range de scores — usado para normalizar para [0, 1].
        """
        # valores claramente normais e claramente anômalos
        normal_values  = np.array([[50.0],[55.0],[60.0],[65.0]], dtype=np.float32)
        anomaly_values = np.array([[85.0],[90.0],[95.0]],        dtype=np.float32)

        normal_scores  = [self._raw_score(v) for v in normal_values]
        anomaly_scores = [self._raw_score(v) for v in anomaly_values]

        all_scores = normal_scores + anomaly_scores
        self._score_min = min(all_scores)
        self._score_max = max(all_scores)

    def _raw_score(self, value: np.ndarray) -> float:
        """Roda scaler → modelo e retorna o score bruto."""
        # garante shape (1, 1) — ONNX exige rank 2
        input_data = np.array(value, dtype=np.float32).reshape(1, 1)

        input_name = self._scaler_session.get_inputs()[0].name
        scaled = self._scaler_session.run(None, {input_name: input_data})[0]

        model_input = self._model_session.get_inputs()[0].name
        output = self._model_session.run(None, {model_input: scaled})

        # IsolationForest ONNX retorna [labels, scores]
        raw = float(np.array(output[1]).flatten()[0])
        return raw

    def _compute_score(self, reading: SensorReading) -> float:
        if self._model_session is None:
            raise RuntimeError("Modelo não carregado. Chame load() antes de predict().")

        value = np.array([[reading.value]], dtype=np.float32)  # shape (1, 1) explícito
        raw   = self._raw_score(value)

        if self._score_max == self._score_min:
            return 0.0

        normalized = (raw - self._score_min) / (self._score_max - self._score_min)
        inverted   = 1.0 - normalized

        return float(max(0.0, min(1.0, inverted)))