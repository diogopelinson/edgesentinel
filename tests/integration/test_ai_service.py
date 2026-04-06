import pytest
import json
import base64
from unittest.mock import patch, MagicMock
from pathlib import Path

import numpy as np

from core.entities import SensorReading
from adapters.inference.remote import RemoteInferenceAdapter


# --- fixtures ---

@pytest.fixture
def black_frame() -> np.ndarray:
    """Frame preto 640x480 — simula câmera sem detecções."""
    return np.zeros((480, 640, 3), dtype=np.uint8)


@pytest.fixture
def reading_with_frame(black_frame) -> SensorReading:
    return SensorReading(
        sensor_id="camera_01",
        name="Camera Entrada",
        value=1.0,
        unit="frame",
        metadata={"frame": black_frame, "source": "simulated"},
    )


@pytest.fixture
def reading_without_frame() -> SensorReading:
    return SensorReading(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        value=85.0,
        unit="°C",
    )


# --- testes do RemoteInferenceAdapter ---

class TestRemoteInferenceAdapter:

    def test_load_warns_when_service_unavailable(self):
        """load() não deve travar quando o serviço está offline."""
        adapter = RemoteInferenceAdapter(
            model_id="yolo_v8n",
            service_url="http://localhost:9999",   # porta inexistente
        )
        # não deve lançar exceção
        adapter.load("")

    def test_load_warns_when_model_not_in_service(self):
        """load() deve avisar se o model_id não existe no serviço."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([
            {"id": "yolo_v8n", "type": "yolo", "status": "loaded"}
        ]).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            adapter = RemoteInferenceAdapter(
                model_id="modelo_inexistente",
                service_url="http://localhost:8080",
            )
            adapter.load("")   # não deve travar

    def test_predict_returns_zero_score_when_service_down(self, reading_without_frame):
        """predict() com serviço offline deve retornar RuntimeError."""
        adapter = RemoteInferenceAdapter(
            model_id="yolo_v8n",
            service_url="http://localhost:9999",
        )
        with pytest.raises(RuntimeError, match="Falha ao chamar AI Service"):
            adapter.predict(reading_without_frame)

    def test_predict_with_sensor_value_builds_correct_payload(self, reading_without_frame):
        """Payload para sensor_value deve conter o campo correto."""
        adapter = RemoteInferenceAdapter(
            model_id="anomaly_onnx",
            service_url="http://localhost:8080",
        )
        payload = adapter._build_payload(reading_without_frame)

        assert payload["model_id"] == "anomaly_onnx"
        assert "sensor_value" in payload
        assert payload["sensor_value"] == 85.0
        assert "frame_b64" not in payload

    def test_predict_with_frame_builds_base64_payload(self, reading_with_frame):
        """Payload para frame deve conter frame_b64."""
        adapter = RemoteInferenceAdapter(
            model_id="yolo_v8n",
            service_url="http://localhost:8080",
        )
        payload = adapter._build_payload(reading_with_frame)

        assert payload["model_id"] == "yolo_v8n"
        assert "frame_b64" in payload
        assert "sensor_value" not in payload

        # verifica que é base64 válido
        decoded = base64.b64decode(payload["frame_b64"])
        assert len(decoded) > 0

    def test_predict_maps_detections_to_anomaly_score(self, reading_without_frame):
        """Detecções retornadas pelo serviço viram AnomalyScore."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "model_id": "yolo_v8n",
            "detections": [
                {"class_name": "person", "confidence": 0.91, "bbox": []}
            ],
            "inference_latency_ms": 150.0,
            "timestamp": 1712188800.0,
            "has_detections": True,
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            adapter = RemoteInferenceAdapter(
                model_id="yolo_v8n",
                service_url="http://localhost:8080",
                threshold=0.5,
            )
            score = adapter.predict(reading_without_frame)

        assert score.score == pytest.approx(0.91, rel=0.01)
        assert score.is_anomaly is True
        assert score.model_id == "remote:yolo_v8n"
        assert "remote_detections" in score.reading.metadata

    def test_predict_no_detections_returns_zero_score(self, reading_without_frame):
        """Sem detecções, score deve ser 0.0 e is_anomaly False."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "model_id": "yolo_v8n",
            "detections": [],
            "inference_latency_ms": 50.0,
            "timestamp": 1712188800.0,
            "has_detections": False,
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            adapter = RemoteInferenceAdapter(
                model_id="yolo_v8n",
                service_url="http://localhost:8080",
                threshold=0.5,
            )
            score = adapter.predict(reading_without_frame)

        assert score.score == 0.0
        assert score.is_anomaly is False

    def test_predict_stores_latency_in_metadata(self, reading_without_frame):
        """Latência de inferência do serviço deve chegar no metadata."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "model_id": "yolo_v8n",
            "detections": [],
            "inference_latency_ms": 178.42,
            "timestamp": 1712188800.0,
            "has_detections": False,
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            adapter = RemoteInferenceAdapter(
                model_id="yolo_v8n",
                service_url="http://localhost:8080",
            )
            score = adapter.predict(reading_without_frame)

        assert score.reading.metadata["inference_latency_ms"] == 178.42

    def test_http_error_raises_runtime_error(self, reading_without_frame):
        """Erro HTTP 500 do serviço deve virar RuntimeError."""
        import urllib.error
        http_error = urllib.error.HTTPError(
            url="http://localhost:8080/predict",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=MagicMock(read=lambda: b'{"detail":"model error"}'),
        )

        with patch("urllib.request.urlopen", side_effect=http_error):
            adapter = RemoteInferenceAdapter(
                model_id="yolo_v8n",
                service_url="http://localhost:8080",
            )
            with pytest.raises(RuntimeError, match="500"):
                adapter.predict(reading_without_frame)


# --- testes do SimulatedCameraSensor ---

class TestSimulatedCameraSensor:

    def test_person_mode_generates_rgb_frame(self):
        from adapters.sensors.camera_simulated import SimulatedCameraSensor
        sensor  = SimulatedCameraSensor("cam", mode="person")
        reading = sensor.read()

        frame = reading.metadata["frame"]
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    def test_noise_mode_generates_nonzero_frame(self):
        from adapters.sensors.camera_simulated import SimulatedCameraSensor
        sensor  = SimulatedCameraSensor("cam", mode="noise")
        reading = sensor.read()

        frame = reading.metadata["frame"]
        assert frame.sum() > 0   # ruído não é tudo zero

    def test_blank_mode_generates_zero_frame(self):
        from adapters.sensors.camera_simulated import SimulatedCameraSensor
        sensor  = SimulatedCameraSensor("cam", mode="blank")
        reading = sensor.read()

        frame = reading.metadata["frame"]
        assert frame.sum() == 0

    def test_reading_value_is_one_on_success(self):
        from adapters.sensors.camera_simulated import SimulatedCameraSensor
        sensor  = SimulatedCameraSensor("cam")
        reading = sensor.read()
        assert reading.value == 1.0

    def test_frame_count_increments(self):
        from adapters.sensors.camera_simulated import SimulatedCameraSensor
        sensor = SimulatedCameraSensor("cam")
        sensor.read()
        sensor.read()
        reading = sensor.read()
        assert reading.metadata["frame_count"] == 3

    def test_is_always_available(self):
        from adapters.sensors.camera_simulated import SimulatedCameraSensor
        sensor = SimulatedCameraSensor("cam")
        assert sensor.is_available() is True