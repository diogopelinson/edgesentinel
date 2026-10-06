import logging

import pytest
from unittest.mock import patch

from adapters.sensors.cpu_temp import CpuTemperatureSensor


class TestCpuTemperatureAvailability:
    """
    A sensor signals absent hardware through is_available(), never by raising
    an exception on construction — core/ports.py:16 defines is_available()
    for exactly that, and it is unreachable if __init__ blows up.

    A contract valid for every sensor: hardware discovery is lazy.
    """

    def test_construction_succeeds_without_thermal_hardware(self):
        """Constructing on a host with no temperature source must not raise."""
        with patch("pathlib.Path.exists", return_value=False):
            CpuTemperatureSensor()

    def test_is_available_is_false_without_thermal_hardware(self):
        with patch("pathlib.Path.exists", return_value=False):
            sensor = CpuTemperatureSensor()
            assert sensor.is_available() is False

    def test_read_names_the_attempted_paths(self):
        """
        With no hardware, read() fails — but the message has to say where it
        looked, otherwise diagnosis turns into guesswork.
        """
        with patch("pathlib.Path.exists", return_value=False):
            sensor = CpuTemperatureSensor()
            with pytest.raises(RuntimeError) as exc:
                sensor.read()

        message = str(exc.value)
        assert "/sys/class/thermal/thermal_zone0/temp" in message
        assert "/usr/bin/vcgencmd" in message

    def test_reads_normally_when_thermal_path_exists(self):
        """Regression: with hardware present, the behavior does not change."""
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value="72500\n"):
            sensor  = CpuTemperatureSensor()
            reading = sensor.read()

        assert reading.value == pytest.approx(72.5)
        assert reading.unit == "°C"
        assert reading.sensor_id == "cpu_temp"

    def test_hardware_appearing_after_construction_is_picked_up(self):
        """
        Lazy discovery means a sensor built with no hardware starts working if
        the hardware shows up later — the opposite of resolving the path once
        and for all in __init__.
        """
        with patch("pathlib.Path.exists", return_value=False):
            sensor = CpuTemperatureSensor()
            assert sensor.is_available() is False

        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value="65000\n"):
            assert sensor.is_available() is True
            assert sensor.read().value == pytest.approx(65.0)


class TestBuilderTreatsMissingHardwareAsUnavailable:
    """
    The builder has two distinct paths: an unavailable sensor is a WARNING and
    it carries on, a construction failure is an ERROR. Absent hardware is the
    first case.
    """

    def test_missing_hardware_logs_unavailable_not_construction_failure(self, caplog):
        from cli.builder import _build_sensors
        from config.schema import EdgeSentinelConfig, SensorConfig, CameraConfig

        config = EdgeSentinelConfig(
            sensors=[SensorConfig(id="cpu_temp", type="cpu_temperature")],
            rules=[],
            actions=[],
            cameras=[CameraConfig(sensor_id="cam", source="x", simulated=True)],
        )

        with (
            patch("pathlib.Path.exists", return_value=False),
            caplog.at_level(logging.WARNING, logger="edgesentinel.builder"),
        ):
            sensors = _build_sensors(config)

        assert sensors == []
        assert "não disponível nesse hardware" in caplog.text
        assert "Falha ao construir sensor" not in caplog.text
