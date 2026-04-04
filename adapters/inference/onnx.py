from __future__ import annotations
import numpy as np

from adapters.inference.base import BaseInferenceAdapter
from core.entities import SensorReading


class ONNXInferenceAdapter(BaseInferenceAdapter):
    """
    Backend ONNX Runtime.

    Espera um modelo treinado para detecção de anomalia que:
    - recebe um array 1D com o valor do sensor normalizado
    - devolve um score entre 0.0 e 1.0

    Compatível com modelos exportados do scikit-learn, PyTorch ou qualquer
    framework que suporte exportação para ONNX.
    """

    def __init__(self, threshold: float = 0.7) -> None:
        super().__init__(model_id="onnx", threshold=threshold)
        self._session = None    # carregado em load(), não no __init__

    def load(self, model_path: str) -> None:
        """
        Carrega o modelo ONNX do disco.
        Separado do __init__ para lazy loading — o modelo só ocupa
        memória quando o usuário realmente habilita inferência.
        """
        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError(
                "onnxruntime não instalado. "
                "Execute: pip install onnxruntime"
            )

        self._session = ort.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
        )

    def _compute_score(self, reading: SensorReading) -> float:
        if self._session is None:
            raise RuntimeError("Modelo não carregado. Chame load() antes de predict().")

        # Normaliza o valor para [0, 1] assumindo range típico de sensor
        # Em produção, isso viria de um scaler salvo junto com o modelo
        input_data = np.array([[reading.value]], dtype=np.float32)

        input_name = self._session.get_inputs()[0].name
        output = self._session.run(None, {input_name: input_data})

        # Espera saída no formato [[score]] ou [score]
        score = float(np.array(output[0]).flatten()[0])
        return max(0.0, min(1.0, score))    # clamp entre 0 e 1