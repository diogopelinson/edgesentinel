from __future__ import annotations
import json
import logging
import urllib.request
import urllib.error
import base64

import numpy as np

from core.ports import InferencePort
from core.entities import SensorReading, AnomalyScore

logger = logging.getLogger("edgesentinel.inference.remote")


class RemoteInferenceAdapter(InferencePort):
    """
    Adapter que delega inferência para o AI Inference Service via HTTP.
    O edgesentinel não sabe se o modelo é YOLO, ONNX ou qualquer outro —
    só envia o frame/valor e recebe um AnomalyScore.
    """

    def __init__(
        self,
        model_id: str,
        service_url: str = "http://localhost:8080",
        threshold: float = 0.5,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.model_id     = model_id
        self._service_url = service_url.rstrip("/")
        self.threshold    = threshold
        self._timeout     = timeout_seconds

    def load(self, model_path: str) -> None:
        """Verifica se o serviço está disponível e o modelo existe."""
        try:
            url = f"{self._service_url}/models"
            with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                models = json.loads(resp.read())

            available = [m["id"] for m in models]
            if self.model_id not in available:
                logger.warning(
                    f"Modelo '{self.model_id}' não encontrado no AI Service. "
                    f"Disponíveis: {available}"
                )
            else:
                logger.info(
                    f"RemoteInferenceAdapter pronto — "
                    f"model={self.model_id} service={self._service_url}"
                )
        except Exception as e:
            logger.warning(f"AI Service indisponível: {e}. Continuando mesmo assim.")

    def predict(self, reading: SensorReading) -> AnomalyScore:
        payload = self._build_payload(reading)
        result  = self._post_predict(payload)
        score   = result.get("has_detections", False)
        confidence = result.get("detections", [{}])[0].get("confidence", 0.0) if result.get("detections") else 0.0

        return AnomalyScore(
            score=round(confidence, 4),
            threshold=self.threshold,
            is_anomaly=confidence >= self.threshold,
            model_id=f"remote:{self.model_id}",
            reading=SensorReading(
                sensor_id=reading.sensor_id,
                name=reading.name,
                value=confidence,
                unit="confidence",
                metadata={
                    **reading.metadata,
                    "remote_detections": result.get("detections", []),
                    "inference_latency_ms": result.get("inference_latency_ms", 0),
                },
            ),
        )

    def _build_payload(self, reading: SensorReading) -> dict:
        payload = {"model_id": self.model_id}

        frame = reading.metadata.get("frame")
        if frame is not None:
            _, buf = __import__("cv2").imencode(".jpg", frame)  # type: ignore[import]
            payload["frame_b64"] = base64.b64encode(buf).decode()
        elif reading.sensor_id != "frame":
            payload["sensor_value"] = reading.value

        return payload

    def _post_predict(self, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            url=f"{self._service_url}/predict",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f"AI Service retornou {e.code}: {body}")
        except Exception as e:
            raise RuntimeError(f"Falha ao chamar AI Service: {e}")