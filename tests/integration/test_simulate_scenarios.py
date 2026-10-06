from unittest.mock import MagicMock
from core.ports import ActionPort
from core.rules import Rule, Condition
from adapters.sensors.simulated import SimulatedSensor
from adapters.inference.dummy import DummyInferenceAdapter
from application.engine import RuleEngine
from application.pipeline import Pipeline


class TestSimulatedSensor:

    def test_normal_scenario_stays_within_range(self):
        """The normal scenario must keep the temperature between 45°C and 70°C."""
        sensor = SimulatedSensor(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            unit="°C",
            base_value=58.0,
            amplitude=4.0,
            scenario="normal",
        )
        readings = [sensor.read().value for _ in range(50)]

        assert all(45.0 <= v <= 70.0 for v in readings), (
            f"Valor fora do range esperado: min={min(readings):.1f} max={max(readings):.1f}"
        )

    def test_stress_scenario_increases_over_time(self):
        """The stress scenario must produce a higher value with an explicit ramp."""
        sensor = SimulatedSensor(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            unit="°C",
            base_value=60.0,
            amplitude=2.0,
            scenario="stress",
        )
        # manipulates _start to simulate that 30 seconds have passed
        import time
        sensor._start = time.monotonic() - 30.0

        reading = sensor.read()
        # with 30s of ramp: base(60) + ramp(30*0.5=15) = ~75°C
        assert reading.value > 70.0, (
            f"Após 30s de stress, esperava >70°C, got {reading.value:.1f}°C"
        )

    def test_spike_scenario_produces_high_values(self):
        """The spike scenario must produce at least one high value in 30 readings."""
        sensor = SimulatedSensor(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            unit="°C",
            base_value=55.0,
            amplitude=3.0,
            scenario="spike",
        )

        readings = [sensor.read().value for _ in range(30)]
        max_value = max(readings)

        # spike adds +25°C — there must be at least one high value
        assert max_value > 70.0, (
            f"Cenário spike deveria produzir valores altos, max foi {max_value:.1f}°C"
        )

    def test_sensor_is_always_available(self):
        """SimulatedSensor must always be available."""
        sensor = SimulatedSensor("cpu_temp", "CPU Temp", "°C", base_value=58.0)
        assert sensor.is_available() is True

    def test_reading_has_correct_metadata(self):
        """The reading must have the right sensor_id, unit and timestamp."""
        sensor = SimulatedSensor(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            unit="°C",
            base_value=58.0,
        )
        reading = sensor.read()

        assert reading.sensor_id == "cpu_temp"
        assert reading.name     == "CPU Temperature"
        assert reading.unit     == "°C"
        assert reading.timestamp > 0

    def test_cpu_usage_clamped_to_100(self):
        """CPU usage in the stress scenario must not exceed 100%."""
        sensor = SimulatedSensor(
            sensor_id="cpu_usage",
            name="CPU Usage",
            unit="%",
            base_value=95.0,
            amplitude=10.0,
            scenario="stress",
        )
        readings = [sensor.read().value for _ in range(30)]
        assert all(v <= 100.0 for v in readings), (
            f"CPU usage ultrapassou 100%: max={max(readings):.1f}"
        )


class TestScenarioEndToEnd:

    def test_stress_eventually_triggers_rule(self):
        """
        The stress scenario fires a rule when the ramp accumulates enough time.
        Simulates the passage of time by manipulating the sensor's _start.
        """
        import time
        sensor = SimulatedSensor(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            unit="°C",
            base_value=60.0,
            amplitude=2.0,
            scenario="stress",
        )
        # simulates 25 seconds of operation — the ramp adds ~12.5°C
        sensor._start = time.monotonic() - 25.0

        rule = Rule(
            name="alta_temperatura",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=70.0),
            action_ids=["log"],
            cooldown_seconds=0.0,
        )
        mock_action = MagicMock(spec=ActionPort)
        engine   = RuleEngine(rules=[rule], actions={"log": mock_action})
        pipeline = Pipeline(
            sensor=sensor,
            engine=engine,
            inference=DummyInferenceAdapter(),
        )

        triggered = False
        for _ in range(10):
            pipeline.run_once()
            if mock_action.execute.called:
                triggered = True
                break

        assert triggered, "Com 25s de rampa, stress deveria ter disparado a regra"

    def test_normal_scenario_never_triggers_high_temp_rule(self):
        """
        The normal scenario must never fire a temperature rule
        above 75°C — normal values stay between 50°C and 65°C.
        """
        sensor = SimulatedSensor(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            unit="°C",
            base_value=58.0,
            amplitude=4.0,
            scenario="normal",
        )
        rule = Rule(
            name="alta_temperatura",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=0.0,
        )
        mock_action = MagicMock(spec=ActionPort)
        engine   = RuleEngine(rules=[rule], actions={"log": mock_action})
        pipeline = Pipeline(
            sensor=sensor,
            engine=engine,
            inference=DummyInferenceAdapter(),
        )

        for _ in range(100):
            pipeline.run_once()

        mock_action.execute.assert_not_called()
