from typing import Type

from adapters.inference.base import BaseInferenceAdapter
from adapters.inference.dummy import DummyInferenceAdapter
from adapters.inference.onnx import ONNXInferenceAdapter
from adapters.inference.tflite import TFLiteInferenceAdapter


_REGISTRY: dict[str, Type[BaseInferenceAdapter]] = {
    "dummy":  DummyInferenceAdapter,
    "onnx":   ONNXInferenceAdapter,
    "tflite": TFLiteInferenceAdapter,
}


def build_inference(backend: str, model_path: str | None, threshold: float = 0.7) -> BaseInferenceAdapter:
    """
    Instancia o backend correto e carrega o modelo se necessário.

    Exemplo via config:
        backend: onnx
        model_path: /models/anomaly.onnx
    """
    cls = _REGISTRY.get(backend)
    if cls is None:
        supported = ", ".join(_REGISTRY.keys())
        raise ValueError(
            f"Backend de inferência desconhecido: '{backend}'. "
            f"Suportados: {supported}"
        )

    adapter = cls(threshold=threshold)

    if model_path is not None:
        adapter.load(model_path)

    return adapter