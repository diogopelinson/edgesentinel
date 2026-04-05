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


def build_inference(
    backend: str,
    model_path: str | None,
    threshold: float = 0.7,
    **kwargs,
) -> BaseInferenceAdapter:
    """
    Instancia o backend correto e carrega o modelo se necessário.

    Backends locais (dummy, onnx, tflite):
        backend: onnx
        model_path: models/anomaly.onnx

    Backend remoto (AI Inference Service):
        backend: remote
        service_url: http://localhost:8080
        model_id: yolo_v8n
    """
    if backend == "remote":
        from adapters.inference.remote import RemoteInferenceAdapter
        service_url = kwargs.get("service_url", "http://localhost:8080")
        model_id    = kwargs.get("model_id", "yolo_v8n")
        adapter     = RemoteInferenceAdapter(
            model_id=model_id,
            service_url=service_url,
            threshold=threshold,
        )
        adapter.load(model_path or "")
        return adapter

    cls = _REGISTRY.get(backend)
    if cls is None:
        supported = ", ".join(list(_REGISTRY.keys()) + ["remote"])
        raise ValueError(
            f"Backend de inferência desconhecido: '{backend}'. "
            f"Suportados: {supported}"
        )

    adapter = cls(threshold=threshold)

    if model_path is not None:
        adapter.load(model_path)

    return adapter