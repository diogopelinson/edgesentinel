from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
import numpy as np


@dataclass
class Detection:
    """One detection, as any model returns it."""
    class_name: str
    confidence: float
    bbox: list[float] = field(default_factory=list)   # [x1, y1, x2, y2]
    metadata: dict = field(default_factory=dict)


@dataclass
class InferenceResult:
    """The full result of one inference."""
    model_id: str
    detections: list[Detection]
    inference_latency_ms: float
    timestamp: float = field(default_factory=time.time)
    frame_shape: tuple | None = None

    @property
    def max_confidence(self) -> float:
        if not self.detections:
            return 0.0
        return max(d.confidence for d in self.detections)

    @property
    def has_detections(self) -> bool:
        return len(self.detections) > 0


class BaseModel(ABC):
    """The contract every model in the registry has to implement."""

    def __init__(self, model_id: str, confidence_threshold: float = 0.5) -> None:
        self.model_id            = model_id
        self.confidence_threshold = confidence_threshold
        self._loaded             = False

    @abstractmethod
    def load(self, config: dict) -> None:
        """Load the model from disk. Called once at startup."""
        ...

    @abstractmethod
    def predict(self, frame: np.ndarray) -> list[Detection]:
        """Run inference on a numpy HxWxC BGR frame."""
        ...

    def run(self, frame: np.ndarray) -> InferenceResult:
        """Runs predict() and measures its latency. Do not override."""
        start = time.monotonic()
        detections = self.predict(frame)
        latency_ms = (time.monotonic() - start) * 1000

        return InferenceResult(
            model_id=self.model_id,
            detections=detections,
            inference_latency_ms=round(latency_ms, 2),
            frame_shape=frame.shape,
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded
