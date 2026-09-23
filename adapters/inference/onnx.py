from __future__ import annotations
from pathlib import Path
import numpy as np

from adapters.inference.base import BaseInferenceAdapter
from core.entities import SensorReading

SCORE_OUTPUT = "anomaly_score"


class ONNXInferenceAdapter(BaseInferenceAdapter):
    """
    Backend ONNX Runtime para modelos de anomalia com este contrato:

      entrada          : valor bruto do sensor, float32 [N, 1]
      saída 'anomaly_score' : float32 [N, 1], em [0, 1]

    Normalização e regra de score moram no artefato, gerado por
    scripts/train_model.py — o adapter só lê a saída. Assim o agente e o
    AI Inference Service não têm como calcular o score de jeitos diferentes.
    """

    def __init__(self, threshold: float = 0.6) -> None:
        super().__init__(model_id="onnx", threshold=threshold)
        self._session = None
        self._input_name: str | None = None

    def load(self, model_path: str) -> None:
        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError("Execute: pip install onnxruntime") from None

        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"Modelo não encontrado: {path}")

        session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])

        outputs = [o.name for o in session.get_outputs()]
        if SCORE_OUTPUT not in outputs:
            # formato antigo: carregar e seguir reproduziria o score errado
            raise ValueError(
                f"{path} não tem a saída '{SCORE_OUTPUT}' "
                f"(saídas: {', '.join(outputs)}). Modelos gerados por versões "
                f"anteriores precisam ser treinados de novo: "
                f"python scripts/train_model.py"
            )

        self._session    = session
        self._input_name = session.get_inputs()[0].name

    def _compute_score(self, reading: SensorReading) -> float:
        if self._session is None:
            raise RuntimeError("Modelo não carregado. Chame load() antes de predict().")

        value = np.array([[reading.value]], dtype=np.float32)
        (scores,) = self._session.run([SCORE_OUTPUT], {self._input_name: value})

        return float(np.clip(scores.ravel()[0], 0.0, 1.0))
