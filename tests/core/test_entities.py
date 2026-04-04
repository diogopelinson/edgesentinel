import time
import pytest

from core.entities import SensorReading, AnomalyScore, ActionContext


class TestSensorReading:

    def test_creates_with_required_fields(self):
        reading = SensorReading(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            value=72.5,
            unit="°C",
        )
        assert reading.sensor_id == "cpu_temp"
        assert reading.value == 72.5

    def test_timestamp_is_set_automatically(self):
        before = time.time()
        reading = SensorReading(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            value=72.5,
            unit="°C",
        )
        after = time.time()
        assert before <= reading.timestamp <= after

    def test_is_immutable(self):
        reading = SensorReading(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            value=72.5,
            unit="°C",
        )
        with pytest.raises(Exception):
            reading.value = 999  # type: ignore


class TestAnomalyScore:

    def test_is_anomaly_when_score_above_threshold(self, cpu_reading):
        score = AnomalyScore(
            score=0.91,
            threshold=0.7,
            is_anomaly=True,
            model_id="dummy",
            reading=cpu_reading,
        )
        assert score.is_anomaly is True

    def test_not_anomaly_when_score_below_threshold(self, cpu_reading):
        score = AnomalyScore(
            score=0.3,
            threshold=0.7,
            is_anomaly=False,
            model_id="dummy",
            reading=cpu_reading,
        )
        assert score.is_anomaly is False

    def test_carries_original_reading(self, cpu_reading):
        score = AnomalyScore(
            score=0.91,
            threshold=0.7,
            is_anomaly=True,
            model_id="dummy",
            reading=cpu_reading,
        )
        assert score.reading is cpu_reading