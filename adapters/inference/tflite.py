from __future__ import annotations
import numpy as np

from adapters.inference.base import BaseInferenceAdapter
from core.entities import SensorReading


class TFLiteInferenceAdapter(BaseInferenceAdapter):
    """
    TensorFlow Lite backend.

    Lighter than ONNX on SBCs — especially on the Raspberry Pi,
    where an optimized build with NEON (ARM SIMD) acceleration exists.

    Expects the same model contract as the ONNXAdapter:
    1D input with a normalized value, score output in [0, 1].
    """

    def __init__(self, threshold: float = 0.7) -> None:
        super().__init__(model_id="tflite", threshold=threshold)
        self._interpreter = None

    def load(self, model_path: str) -> None:
        try:
            import tflite_runtime.interpreter as tflite
        except ImportError:
            try:
                import tensorflow.lite as tflite
            except ImportError:
                raise ImportError(
                    "Nenhum runtime TFLite encontrado. Execute:\n"
                    "  pip install tflite-runtime   (recomendado para SBCs)\n"
                    "  pip install tensorflow        (alternativa completa)"
                ) from None

        self._interpreter = tflite.Interpreter(model_path=model_path)
        self._interpreter.allocate_tensors()

        self._input_details  = self._interpreter.get_input_details()
        self._output_details = self._interpreter.get_output_details()

    def _compute_score(self, reading: SensorReading) -> float:
        if self._interpreter is None:
            raise RuntimeError("Modelo não carregado. Chame load() antes de predict().")

        input_data = np.array([[reading.value]], dtype=np.float32)
        self._interpreter.set_tensor(self._input_details[0]["index"], input_data)
        self._interpreter.invoke()

        output = self._interpreter.get_tensor(self._output_details[0]["index"])
        score = float(np.array(output).flatten()[0])
        return max(0.0, min(1.0, score))
