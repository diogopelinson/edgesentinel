import logging

import pytest
from unittest.mock import patch

from adapters.sensors.cpu_temp import CpuTemperatureSensor


class TestCpuTemperatureAvailability:
    """
    Um sensor sinaliza ausência de hardware por is_available(), nunca
    levantando exceção na construção — core/ports.py:16 define is_available()
    exatamente para isso, e ele é inalcançável se o __init__ explodir.

    Contrato válido para todo sensor: descoberta de hardware é preguiçosa.
    """

    def test_construction_succeeds_without_thermal_hardware(self):
        """Construir num host sem fonte de temperatura não pode levantar."""
        with patch("pathlib.Path.exists", return_value=False):
            CpuTemperatureSensor()

    def test_is_available_is_false_without_thermal_hardware(self):
        with patch("pathlib.Path.exists", return_value=False):
            sensor = CpuTemperatureSensor()
            assert sensor.is_available() is False

    def test_read_names_the_attempted_paths(self):
        """
        Sem hardware, read() falha — mas a mensagem precisa dizer onde
        procurou, senão o diagnóstico vira adivinhação.
        """
        with patch("pathlib.Path.exists", return_value=False):
            sensor = CpuTemperatureSensor()
            with pytest.raises(RuntimeError) as exc:
                sensor.read()

        message = str(exc.value)
        assert "/sys/class/thermal/thermal_zone0/temp" in message
        assert "/usr/bin/vcgencmd" in message

    def test_reads_normally_when_thermal_path_exists(self):
        """Regressão: com hardware presente, o comportamento não muda."""
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value="72500\n"):
            sensor  = CpuTemperatureSensor()
            reading = sensor.read()

        assert reading.value == pytest.approx(72.5)
        assert reading.unit == "°C"
        assert reading.sensor_id == "cpu_temp"

    def test_hardware_appearing_after_construction_is_picked_up(self):
        """
        Descoberta preguiçosa significa que um sensor construído sem hardware
        passa a funcionar se o hardware aparecer depois — o oposto de resolver
        o caminho uma única vez no __init__.
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
    O builder tem dois caminhos distintos: sensor indisponível é WARNING e
    segue, falha de construção é ERROR. Hardware ausente é o primeiro caso.
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
