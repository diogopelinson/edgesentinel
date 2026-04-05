from __future__ import annotations
import logging
import numpy as np

from core.base import BaseModel, Detection

logger = logging.getLogger("ai_service.models.yolo")


class YOLOModel(BaseModel):
    """
    Wrapper YOLOv8 via ultralytics.
    Filtra por target_classes se configurado.
    """

    def __init__(self, model_id: str, confidence_threshold: float = 0.5) -> None:
        super().__init__(model_id, confidence_threshold)
        self._model         = None
        self._target_classes: list[str] = []

    def load(self, config: dict) -> None:
        from ultralytics import YOLO  # type: ignore[import]

        path = config["path"]
        self._target_classes = config.get("target_classes", [])

        logger.info(f"Carregando YOLO de: {path}")
        self._model = YOLO(path)
        self._loaded = True
        logger.info(f"YOLO '{self.model_id}' pronto.")

    def predict(self, frame: np.ndarray) -> list[Detection]:
        if not self._loaded or self._model is None:
            raise RuntimeError(f"Modelo '{self.model_id}' não carregado.")

        results    = self._model(frame, verbose=False)
        detections = []

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                class_id   = int(box.cls[0])
                class_name = self._model.names[class_id]
                confidence = float(box.conf[0])

                if confidence < self.confidence_threshold:
                    continue

                if self._target_classes and class_name not in self._target_classes:
                    continue

                detections.append(Detection(
                    class_name=class_name,
                    confidence=round(confidence, 4),
                    bbox=box.xyxy[0].tolist(),
                ))

        return detections