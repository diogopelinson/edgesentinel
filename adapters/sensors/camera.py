import time
import logging
from core.ports import SensorPort
from core.entities import SensorReading

logger = logging.getLogger("edgesentinel.sensors.camera")


class CameraSensor(SensorPort):
    """
    A sensor that captures frames from a camera over RTSP, webcam or file.

    The frame is stored in metadata["frame"] as a numpy array.
    The value is always 1.0 when the frame is captured successfully — it is
    the YOLOInferenceAdapter that extracts meaning from the frame.

    Supported sources:
        rtsp://user:password@ip:port/stream   → IP camera
        0, 1, 2...                            → local webcam
        /path/video.mp4                       → video file
    """

    def __init__(
        self,
        sensor_id: str,
        source: str | int,
        name: str = "Camera",
        fps_limit: float = 1.0,
    ) -> None:
        self.sensor_id = sensor_id
        self.source    = source
        self.name      = name
        self.unit      = "frame"
        self._fps_limit = fps_limit
        self._cap       = None
        self._last_read = 0.0

    def read(self) -> SensorReading:
        self._ensure_connected()

        # respects fps_limit — does not capture faster than necessary
        elapsed = time.monotonic() - self._last_read
        min_interval = 1.0 / self._fps_limit
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        ret, frame = self._cap.read()

        if not ret or frame is None:
            # tries to reconnect once before failing
            logger.warning(f"[{self.sensor_id}] Frame inválido — tentando reconectar...")
            self._reconnect()
            ret, frame = self._cap.read()
            if not ret:
                raise RuntimeError(f"Falha ao capturar frame de: {self.source}")

        self._last_read = time.monotonic()

        return SensorReading(
            sensor_id=self.sensor_id,
            name=self.name,
            value=1.0,           # 1.0 = frame captured, 0.0 would be a failure
            unit=self.unit,
            metadata={
                "frame":  frame,                           # numpy array HxWxC
                "source": str(self.source),
                "shape":  frame.shape,
            },
        )

    def is_available(self) -> bool:
        try:
            self._ensure_connected()
            return self._cap is not None and self._cap.isOpened()
        except Exception:
            return False

    def release(self) -> None:
        """Releases the camera resource."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # --- private methods ---

    def _ensure_connected(self) -> None:
        if self._cap is None or not self._cap.isOpened():
            self._connect()

    def _connect(self) -> None:
        try:
            import cv2  # type: ignore[import]
        except ImportError:
            raise ImportError(
                "opencv-python não instalado. "
                "Execute: pip install opencv-python"
            ) from None

        logger.info(f"[{self.sensor_id}] Conectando em: {self.source}")
        self._cap = cv2.VideoCapture(self.source)

        if not self._cap.isOpened():
            raise RuntimeError(
                f"Não foi possível conectar na fonte: {self.source}\n"
                f"Verifique a URL RTSP, índice da webcam ou caminho do arquivo."
            )

        logger.info(f"[{self.sensor_id}] Conectado com sucesso.")

    def _reconnect(self) -> None:
        self.release()
        time.sleep(2.0)
        self._connect()
