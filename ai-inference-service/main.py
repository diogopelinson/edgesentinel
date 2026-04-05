from __future__ import annotations
import logging
import base64
import time
from contextlib import asynccontextmanager

import cv2  # type: ignore[import]
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel as PydanticModel

from core.registry import ModelRegistry
from core.base import InferenceResult
from exporter.otel import ServiceExporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_service")

registry = ModelRegistry()
exporter = ServiceExporter()


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.load_from_config("models.yaml")
    exporter.start()
    logger.info("AI Inference Service pronto.")
    yield
    logger.info("AI Inference Service encerrado.")


app = FastAPI(
    title="edgesentinel AI Inference Service",
    description="Serviço de inferência plug-and-play para modelos de visão e anomalia",
    version="0.1.0",
    lifespan=lifespan,
)


# --- schemas Pydantic ---

class PredictRequest(PydanticModel):
    model_id: str
    stream_url: str | None = None      # RTSP URL — captura um frame
    frame_b64: str | None = None       # frame em base64 — uso direto
    sensor_value: float | None = None  # para modelos de anomalia de sensor


class DetectionOut(PydanticModel):
    class_name: str
    confidence: float
    bbox: list[float] = []
    metadata: dict = {}


class PredictResponse(PydanticModel):
    model_id: str
    detections: list[DetectionOut]
    inference_latency_ms: float
    timestamp: float
    has_detections: bool


# --- endpoints ---

@app.get("/health")
def health():
    return {"status": "ok", "models": len(registry.list_models())}


@app.get("/models")
def list_models():
    return registry.list_models()


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest):
    try:
        model = registry.get(request.model_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    frame = _get_frame(request)
    result: InferenceResult = model.run(frame)

    exporter.record_inference(
        model_id=request.model_id,
        latency_ms=result.inference_latency_ms,
        detections=len(result.detections),
    )

    return PredictResponse(
        model_id=result.model_id,
        detections=[
            DetectionOut(
                class_name=d.class_name,
                confidence=d.confidence,
                bbox=d.bbox,
                metadata=d.metadata,
            )
            for d in result.detections
        ],
        inference_latency_ms=result.inference_latency_ms,
        timestamp=result.timestamp,
        has_detections=result.has_detections,
    )


# --- helpers ---

def _get_frame(request: PredictRequest) -> np.ndarray:
    """Resolve o frame a partir das opções do request."""

    if request.sensor_value is not None:
        return np.array([[request.sensor_value]], dtype=np.float32)

    if request.frame_b64:
        data  = base64.b64decode(request.frame_b64)
        arr   = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise HTTPException(status_code=400, detail="frame_b64 inválido")
        return frame

    if request.stream_url:
        return _capture_frame(request.stream_url)

    raise HTTPException(
        status_code=400,
        detail="Forneça stream_url, frame_b64 ou sensor_value"
    )


def _capture_frame(url: str) -> np.ndarray:
    cap = cv2.VideoCapture(url)
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível capturar frame de: {url}"
        )
    return frame