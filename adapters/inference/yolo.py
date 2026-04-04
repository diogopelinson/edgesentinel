from __future__ import annotations
import logging
import numpy as np
from core.ports import InferencePort
from core.entities import SensorReading, AnomalyScore

logger = logging.getLogger("edgesentinel.inference.yolo")


class YOLOInferenceAdapter(InferencePort):

    def __init__(
        self,
        threshold: float = 0.5,
        target_classes: list[str] | None = None,
    ) -> None:
        self.model_id        = "yolo"
        self.threshold       = threshold
        self._model          = None
        self._target_classes = target_classes or []

    def load(self, model_path: str) -> None:
        try:
            from ultralytics import YOLO  # type: ignore[import]
        except ImportError:
            raise ImportError(
                "ultralytics não instalado. "
                "Execute: pip install edgesentinel[camera]"
            )
        logger.info(f"Carregando modelo YOLO de: {model_path}")
        self._model = YOLO(model_path)
        logger.info("Modelo YOLO carregado.")

    def predict(self, reading: SensorReading) -> AnomalyScore:
        if self._model is None:
            raise RuntimeError("Modelo não carregado. Chame load() antes de predict().")

        frame = reading.metadata.get("frame")
        if frame is None:
            raise ValueError(
                f"SensorReading '{reading.sensor_id}' não contém 'frame' no metadata."
            )

        detections = self._run_yolo(frame)
        score, matched = self._evaluate_detections(detections)

        enriched_reading = SensorReading(
            sensor_id=reading.sensor_id,
            name=reading.name,
            value=score,
            unit="confidence",
            metadata={
                **reading.metadata,
                "detections":      detections,
                "matched_classes": matched,
            },
        )

        return AnomalyScore(
            score=score,
            threshold=self.threshold,
            is_anomaly=score >= self.threshold,
            model_id=self.model_id,
            reading=enriched_reading,
        )

    def _run_yolo(self, frame: np.ndarray) -> list[dict]:
        results    = self._model(frame, verbose=False)
        detections = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                class_id   = int(box.cls[0])
                class_name = self._model.names[class_id]
                confidence = float(box.conf[0])
                bbox       = box.xyxy[0].tolist()
                detections.append({
                    "class_name": class_name,
                    "confidence": round(confidence, 4),
                    "bbox":       bbox,
                })

        return detections

    def _evaluate_detections(
        self,
        detections: list[dict],
    ) -> tuple[float, list[str]]:
        if not detections:
            return 0.0, []

        relevant = (
            detections if not self._target_classes
            else [d for d in detections if d["class_name"] in self._target_classes]
        )

        if not relevant:
            return 0.0, []

        matched_classes = list({d["class_name"] for d in relevant})
        max_confidence  = max(d["confidence"] for d in relevant)
        return max_confidence, matched_classes