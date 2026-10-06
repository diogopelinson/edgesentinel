import pytest

from core.entities import SensorReading, AnomalyScore
from core.rules import Rule, Condition


@pytest.fixture
def cpu_reading() -> SensorReading:
    """Default temperature reading for use in the tests."""
    return SensorReading(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        value=72.5,
        unit="°C",
    )


@pytest.fixture
def high_cpu_reading() -> SensorReading:
    """Reading above the threshold — must fire rules."""
    return SensorReading(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        value=82.0,
        unit="°C",
    )



@pytest.fixture
def anomaly_score(cpu_reading) -> AnomalyScore:
    """Score of a confirmed anomaly."""
    return AnomalyScore(
        score=0.91,
        threshold=0.7,
        is_anomaly=True,
        model_id="dummy",
        reading=cpu_reading,
    )


@pytest.fixture
def normal_score(cpu_reading) -> AnomalyScore:
    """Normal score — below the threshold."""
    return AnomalyScore(
        score=0.2,
        threshold=0.7,
        is_anomaly=False,
        model_id="dummy",
        reading=cpu_reading,
    )


@pytest.fixture
def simple_rule() -> Rule:
    """Simple rule: cpu_temp > 75."""
    return Rule(
        name="alta_temperatura",
        condition=Condition(
            sensor_id="cpu_temp",
            operator=">",
            threshold=75.0,
        ),
        action_ids=["log"],
    )
