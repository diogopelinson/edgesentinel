import time
import logging
import numpy as np
from core.ports import SensorPort
from core.entities import SensorReading

logger = logging.getLogger("edgesentinel.sensors.camera")


class CameraSensor(SensorPort):
    """
    Sensor que captura frames de uma câmera via RTSP, webcam ou arquivo.

    O frame é armazenado em metadata["frame"] como numpy array.
    O value é sempre 1.0 quando o frame é capturado com sucesso — é
    o YOLOInferenceAdapter que vai extrair significado do frame.

    Fontes suportadas:
        rtsp://usuario:senha@ip:porta/stream   → câmera IP
        0, 1, 2...                             → webcam local
        /caminho/video.mp4                     → arquivo de vídeo
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

        # respeita o fps_limit — não captura mais rápido que o necessário
        elapsed = time.monotonic() - self._last_read
        min_interval = 1.0 / self._fps_limit
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        ret, frame = self._cap.read()

        if not ret or frame is None:
            # tenta reconectar uma vez antes de falhar
            logger.warning(f"[{self.sensor_id}] Frame inválido — tentando reconectar...")
            self._reconnect()
            ret, frame = self._cap.read()
            if not ret:
                raise RuntimeError(f"Falha ao capturar frame de: {self.source}")

        self._last_read = time.monotonic()

        return SensorReading(
            sensor_id=self.sensor_id,
            name=self.name,
            value=1.0,           # 1.0 = frame capturado, 0.0 seria falha
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
        """Libera o recurso de câmera."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # --- métodos privados ---

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
            )

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