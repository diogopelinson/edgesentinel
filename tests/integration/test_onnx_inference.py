import itertools

import pytest

from adapters.inference.onnx import ONNXInferenceAdapter
from core.entities import SensorReading


def score_of(adapter: ONNXInferenceAdapter, value: float) -> float:
    reading = SensorReading("cpu_temp", "CPU Temperature", float(value), "°C")
    return adapter.predict(reading).score


def strictly_increasing(values: list[float]) -> bool:
    return all(a < b for a, b in itertools.pairwise(values))


@pytest.fixture
def adapter(anomaly_model_path) -> ONNXInferenceAdapter:
    a = ONNXInferenceAdapter(threshold=0.6)
    a.load(str(anomaly_model_path))
    return a


class TestScores:
    """The reference model is trained with normal temperature, ~51 to ~65 °C."""

    def test_normal_temperature_scores_low(self, adapter):
        assert score_of(adapter, 58) < 0.5

    def test_high_temperature_is_an_anomaly(self, adapter):
        result = adapter.predict(SensorReading("cpu_temp", "CPU Temperature", 90.0, "°C"))

        assert result.score > 0.6
        assert result.is_anomaly is True

    def test_scores_keep_rising_above_the_training_range(self, adapter):
        """
        Regression: the IsolationForest falls on the same leaf for any value
        beyond the largest one seen in training, and the old score was 0.9366 for
        everything above ~65 °C — precisely the range that fires rules.
        """
        scores = [score_of(adapter, v) for v in (70, 75, 85, 95, 100)]

        assert strictly_increasing(scores), scores

    def test_scores_keep_rising_below_the_training_range(self, adapter):
        """On the other side it was the same: a fixed 1.0 for everything below ~50 °C."""
        scores = [score_of(adapter, v) for v in (45, 40, 30, 20, 0)]

        assert strictly_increasing(scores), scores

    def test_values_outside_the_training_range_score_at_least_the_boundary(self, adapter, train_model):
        for value in (0, 40, 45, 70, 75, 100):
            assert score_of(adapter, value) >= train_model.SUPPORT_BOUNDARY_SCORE, value

    def test_values_well_inside_the_training_range_score_below_the_boundary(self, adapter, train_model):
        for value in (55, 57, 58, 60, 62):
            assert score_of(adapter, value) < train_model.SUPPORT_BOUNDARY_SCORE, value

    def test_scores_stay_between_zero_and_one(self, adapter):
        for value in range(-100, 301, 20):
            assert 0.0 <= score_of(adapter, value) <= 1.0, value

    def test_model_id_is_onnx(self, adapter):
        reading = SensorReading("cpu_temp", "CPU Temperature", 58.0, "°C")

        assert adapter.predict(reading).model_id == "onnx"


class TestLoading:

    def test_does_not_need_a_scaler_file(self, anomaly_model_path):
        """The normalization is inside the artifact — scaler.onnx no longer exists."""
        assert not (anomaly_model_path.parent / "scaler.onnx").exists()

        ONNXInferenceAdapter().load(str(anomaly_model_path))

    def test_rejects_a_model_without_the_score_output(self, legacy_model_path):
        """
        A model in the old format has to fail loudly: loading it and carrying on
        would reproduce the wrong score in silence.
        """
        with pytest.raises(ValueError) as exc:
            ONNXInferenceAdapter().load(str(legacy_model_path))

        message = str(exc.value)
        assert "anomaly_score" in message
        assert "train_model.py" in message

    def test_missing_file_is_reported(self, tmp_path):
        pytest.importorskip("onnxruntime")

        with pytest.raises(FileNotFoundError):
            ONNXInferenceAdapter().load(str(tmp_path / "nao_existe.onnx"))

    def test_predict_before_load_fails_clearly(self):
        reading = SensorReading("cpu_temp", "CPU Temperature", 58.0, "°C")

        with pytest.raises(RuntimeError, match="load"):
            ONNXInferenceAdapter().predict(reading)
