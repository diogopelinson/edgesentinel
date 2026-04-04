import numpy as np
import time
from core.ports import SensorPort
from core.entities import SensorReading


class SimulatedCameraSensor(SensorPort):
    """
    Sensor de câmera simulado — gera frames sintéticos para testes.
    Não precisa de câmera, OpenCV ou stream RTSP.

    Modos:
        blank  → frame preto puro
        noise  → ruído aleatório (simula câmera com interferência)
        person → frame com retângulo branco simulando uma pessoa detectada
    """

    def __init__(
        self,
        sensor_id: str,
        name: str = "Simulated Camera",
        mode: str = "noise",          # blank | noise | person
        width: int = 640,
        height: int = 480,
    ) -> None:
        self.sensor_id = sensor_id
        self.name      = name
        self.unit      = "frame"
        self._mode     = mode
        self._width    = width
        self._height   = height
        self._frame_count = 0

    def read(self) -> SensorReading:
        self._frame_count += 1
        frame = self._generate_frame()

        return SensorReading(
            sensor_id=self.sensor_id,
            name=self.name,
            value=1.0,
            unit=self.unit,
            metadata={
                "frame":       frame,
                "source":      f"simulated:{self._mode}",
                "shape":       frame.shape,
                "frame_count": self._frame_count,
            },
        )

    def is_available(self) -> bool:
        return True

    def _generate_frame(self) -> np.ndarray:
        if self._mode == "blank":
            return np.zeros((self._height, self._width, 3), dtype=np.uint8)

        if self._mode == "noise":
            return np.random.randint(
                0, 255,
                (self._height, self._width, 3),
                dtype=np.uint8,
            )

        if self._mode == "person":
            frame = np.zeros((self._height, self._width, 3), dtype=np.uint8)
            # retângulo branco simulando bounding box de pessoa
            x1, y1, x2, y2 = 200, 100, 300, 400
            frame[y1:y2, x1:x2] = 255
            return frame

        return np.zeros((self._height, self._width, 3), dtype=np.uint8)