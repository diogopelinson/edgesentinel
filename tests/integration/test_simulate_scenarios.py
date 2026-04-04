import pytest
from unittest.mock import MagicMock
from core.ports import ActionPort
from core.rules import Rule, Condition
from adapters.sensors.simulated import SimulatedSensor
from adapters.inference.dummy import DummyInferenceAdapter
from application.engine import RuleEngine
from application.pipeline import Pipeline


class TestSimulatedSensor:

    def test_normal_scenario_stays_within_range(self):
        """Cenário normal deve manter temperatura entre 45°C e 70°C."""
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
        """Cenário stress deve produzir valor maior com rampa explícita."""
        sensor = SimulatedSensor(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            unit="°C",
            base_value=60.0,
            amplitude=2.0,
            scenario="stress",
        )
        # manipula o _start para simular que 30 segundos passaram
        import time
        sensor._start = time.monotonic() - 30.0

        reading = sensor.read()
        # com 30s de rampa: base(60) + ramp(30*0.5=15) = ~75°C
        assert reading.value > 70.0, (
            f"Após 30s de stress, esperava >70°C, got {reading.value:.1f}°C"
        )

    def test_spike_scenario_produces_high_values(self):
        """Cenário spike deve produzir pelo menos um valor alto em 30 leituras."""
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

        # spike adiciona +25°C — deve haver pelo menos um valor alto
        assert max_value > 70.0, (
            f"Cenário spike deveria produzir valores altos, max foi {max_value:.1f}°C"
        )

    def test_sensor_is_always_available(self):
        """SimulatedSensor deve estar sempre disponível."""
        sensor = SimulatedSensor("cpu_temp", "CPU Temp", "°C", base_value=58.0)
        assert sensor.is_available() is True

    def test_reading_has_correct_metadata(self):
        """Leitura deve ter sensor_id, unit e timestamp corretos."""
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
        """CPU usage no cenário stress não deve ultrapassar 100%."""
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
        Cenário stress dispara regra quando rampa acumula tempo suficiente.
        Simula passagem de tempo manipulando _start do sensor.
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
        # simula 25 segundos de operação — rampa adiciona ~12.5°C
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
        Cenário normal nunca deve disparar regra de temperatura
        acima de 75°C — valores normais ficam entre 50°C e 65°C.
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