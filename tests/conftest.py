import time
import pytest

from core.entities import SensorReading, AnomalyScore, ActionContext
from core.rules import Rule, Condition


@pytest.fixture
def cpu_reading() -> SensorReading:
    """Leitura de temperatura padrão para uso nos testes."""
    return SensorReading(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        value=72.5,
        unit="°C",
    )


@pytest.fixture
def high_cpu_reading() -> SensorReading:
    """Leitura acima do threshold — deve disparar regras."""
    return SensorReading(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        value=82.0,
        unit="°C",
    )



@pytest.fixture
def anomaly_score(cpu_reading) -> AnomalyScore:
    """Score de anomalia confirmada."""
    return AnomalyScore(
        score=0.91,
        threshold=0.7,
        is_anomaly=True,
        model_id="dummy",
        reading=cpu_reading,
    )


@pytest.fixture
def normal_score(cpu_reading) -> AnomalyScore:
    """Score normal — abaixo do threshold."""
    return AnomalyScore(
        score=0.2,
        threshold=0.7,
        is_anomaly=False,
        model_id="dummy",
        reading=cpu_reading,
    )


@pytest.fixture
def simple_rule() -> Rule:
    """Regra simples: cpu_temp > 75."""
    return Rule(
        name="alta_temperatura",
        condition=Condition(
            sensor_id="cpu_temp",
            operator=">",
            threshold=75.0,
        ),
        action_ids=["log"],
    )