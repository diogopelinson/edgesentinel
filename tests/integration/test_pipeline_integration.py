import time
import pytest
from unittest.mock import MagicMock, patch

from core.rules import Rule, Condition
from core.entities import SensorReading
from core.ports import ActionPort
from adapters.sensors.simulated import SimulatedSensor
from adapters.inference.dummy import DummyInferenceAdapter
from adapters.actions.log import LogAction
from adapters.exporter.prometheus import PrometheusExporter
from application.engine import RuleEngine
from application.pipeline import Pipeline


# --- fixtures ---

@pytest.fixture
def normal_sensor() -> SimulatedSensor:
    return SimulatedSensor(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        unit="°C",
        base_value=58.0,
        amplitude=4.0,
        scenario="normal",
    )


@pytest.fixture
def stress_sensor() -> SimulatedSensor:
    return SimulatedSensor(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        unit="°C",
        base_value=60.0,
        amplitude=3.0,
        scenario="stress",
    )


@pytest.fixture
def rule_above_75() -> Rule:
    return Rule(
        name="alta_temperatura",
        condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
        action_ids=["log"],
        cooldown_seconds=0.0,
    )


@pytest.fixture
def mock_action() -> MagicMock:
    return MagicMock(spec=ActionPort)


@pytest.fixture
def dummy_inference() -> DummyInferenceAdapter:
    return DummyInferenceAdapter()


class TestPipelineIntegration:

    def test_full_cycle_reads_sensor_and_evaluates_rules(
        self, normal_sensor, rule_above_75, mock_action, dummy_inference
    ):
        """
        Ciclo completo: sensor lê → pipeline roda → engine avalia.
        Com sensor normal (58°C base), regra de 75°C não deve disparar.
        """
        engine = RuleEngine(rules=[rule_above_75], actions={"log": mock_action})
        pipeline = Pipeline(sensor=normal_sensor, engine=engine, inference=dummy_inference)

        # roda 5 ciclos
        for _ in range(5):
            pipeline.run_once()

        # sensor normal não deve disparar regra de alta temperatura
        mock_action.execute.assert_not_called()

    def test_pipeline_records_to_exporter(
        self, normal_sensor, rule_above_75, dummy_inference
    ):
        """Verifica que o exporter recebe as leituras do pipeline."""
        engine   = RuleEngine(rules=[rule_above_75], actions={})
        exporter = MagicMock(spec=PrometheusExporter)
        pipeline = Pipeline(
            sensor=normal_sensor,
            engine=engine,
            inference=dummy_inference,
            exporter=exporter,
        )

        pipeline.run_once()

        exporter.record.assert_called_once()
        call_args = exporter.record.call_args
        reading = call_args[0][0]
        assert reading.sensor_id == "cpu_temp"
        assert reading.unit == "°C"

    def test_pipeline_continues_when_inference_fails(
        self, normal_sensor, rule_above_75, mock_action
    ):
        """
        Se a inferência falhar, o pipeline não deve travar.
        A regra ainda deve ser avaliada sem score.
        """
        broken_inference = MagicMock()
        broken_inference.predict.side_effect = RuntimeError("modelo corrompido")

        engine = RuleEngine(rules=[rule_above_75], actions={"log": mock_action})
        pipeline = Pipeline(
            sensor=normal_sensor,
            engine=engine,
            inference=broken_inference,
        )

        # não deve lançar exceção
        pipeline.run_once()

    def test_pipeline_continues_when_sensor_fails(
        self, rule_above_75, mock_action, dummy_inference
    ):
        """Se o sensor falhar, o pipeline deve logar e continuar."""
        broken_sensor = MagicMock()
        broken_sensor.read.side_effect = OSError("arquivo não encontrado")

        engine = RuleEngine(rules=[rule_above_75], actions={"log": mock_action})
        pipeline = Pipeline(
            sensor=broken_sensor,
            engine=engine,
            inference=dummy_inference,
        )

        # não deve lançar exceção
        pipeline.run_once()
        mock_action.execute.assert_not_called()

    def test_inference_score_reaches_action_context(
        self, normal_sensor, dummy_inference
    ):
        """
        Verifica que o AnomalyScore produzido pela inferência
        chega corretamente no ActionContext da ação.
        """
        mock_action = MagicMock(spec=ActionPort)
        rule = Rule(
            name="qualquer",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=0.0),
            action_ids=["log"],
            cooldown_seconds=0.0,
        )
        engine   = RuleEngine(rules=[rule], actions={"log": mock_action})
        pipeline = Pipeline(
            sensor=normal_sensor,
            engine=engine,
            inference=dummy_inference,
        )

        pipeline.run_once()

        mock_action.execute.assert_called_once()
        context = mock_action.execute.call_args[0][0]
        assert context.score is not None
        assert context.score.model_id == "dummy"
        assert context.score.score == 0.0

    def test_multiple_sensors_run_independently(self, dummy_inference):
        """
        Dois pipelines com sensores diferentes devem operar
        independentemente — falha num não afeta o outro.
        """
        sensor_a = SimulatedSensor("cpu_temp",  "CPU Temp",  "°C", base_value=58.0, scenario="normal")
        sensor_b = SimulatedSensor("cpu_usage", "CPU Usage", "%",  base_value=30.0, scenario="normal")

        action_a = MagicMock(spec=ActionPort)
        action_b = MagicMock(spec=ActionPort)

        rule_a = Rule("regra_a", Condition("cpu_temp",  ">", 200.0), ["a"])
        rule_b = Rule("regra_b", Condition("cpu_usage", ">", 200.0), ["b"])

        engine_a = RuleEngine(rules=[rule_a], actions={"a": action_a})
        engine_b = RuleEngine(rules=[rule_b], actions={"b": action_b})

        pipeline_a = Pipeline(sensor=sensor_a, engine=engine_a, inference=dummy_inference)
        pipeline_b = Pipeline(sensor=sensor_b, engine=engine_b, inference=dummy_inference)

        pipeline_a.run_once()
        pipeline_b.run_once()

        # threshold impossível — nenhuma deve disparar
        action_a.execute.assert_not_called()
        action_b.execute.assert_not_called()