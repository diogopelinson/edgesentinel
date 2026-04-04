import pytest
from pathlib import Path
from adapters.inference.onnx import ONNXInferenceAdapter
from core.entities import SensorReading

MODEL_PATH = Path("models/anomaly.onnx")

@pytest.mark.skipif(not MODEL_PATH.exists(), reason="modelo ONNX não gerado")
class TestONNXInferenceAdapter:

    def test_normal_temp_returns_low_score(self):
        adapter = ONNXInferenceAdapter(threshold=0.6)
        adapter.load(str(MODEL_PATH))
        reading = SensorReading(sensor_id="cpu_temp", name="CPU Temperature", value=58.0, unit="°C")
        score = adapter.predict(reading)
        assert score.score < 0.5, f"Temperatura normal deveria ter score baixo, got {score.score}"

    def test_anomalous_temp_returns_high_score(self):
        adapter = ONNXInferenceAdapter(threshold=0.6)
        adapter.load(str(MODEL_PATH))
        reading = SensorReading(sensor_id="cpu_temp", name="CPU Temperature", value=90.0, unit="°C")
        score = adapter.predict(reading)
        assert score.score > 0.6, f"Temperatura anômala deveria ter score alto, got {score.score}"
        assert score.is_anomaly is True

    def test_model_id_is_onnx(self):
        adapter = ONNXInferenceAdapter(threshold=0.6)
        adapter.load(str(MODEL_PATH))
        reading = SensorReading(sensor_id="cpu_temp", name="CPU Temperature", value=58.0, unit="°C")
        score = adapter.predict(reading)
        assert score.model_id == "onnx"