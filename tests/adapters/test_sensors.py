import pytest
from unittest.mock import patch, mock_open

from adapters.sensors.cpu_usage import CpuUsageSensor
from adapters.sensors.memory_usage import MemoryUsageSensor


class TestCpuUsageSensor:

    def test_first_read_returns_zero(self):
        """
        Primeira leitura sem snapshot anterior deve retornar 0.
        Usa patch para simular /proc/stat sem precisar do Linux.
        """
        stat_content = "cpu  1000 0 500 8000 0 0 0 0 0 0\n"

        with patch("builtins.open", mock_open(read_data=stat_content)):
            with patch("pathlib.Path.read_text", return_value=stat_content):
                sensor = CpuUsageSensor()
                reading = sensor.read()
                assert reading.value == 0.0
                assert reading.sensor_id == "cpu_usage"
                assert reading.unit == "%"

    def test_reading_has_correct_fields(self):
        stat_content = "cpu  1000 0 500 8000 0 0 0 0 0 0\n"

        with patch("pathlib.Path.read_text", return_value=stat_content):
            sensor = CpuUsageSensor()
            reading = sensor.read()

            assert reading.name == "CPU Usage"
            assert reading.unit == "%"
            assert 0.0 <= reading.value <= 100.0


class TestMemoryUsageSensor:

    def test_calculates_usage_correctly(self):
        """
        MemTotal: 4GB, MemAvailable: 1GB → uso = 75%
        """
        meminfo = (
            "MemTotal:       4096000 kB\n"
            "MemFree:         512000 kB\n"
            "MemAvailable:   1024000 kB\n"
        )

        with patch("pathlib.Path.read_text", return_value=meminfo):
            sensor = MemoryUsageSensor()
            reading = sensor.read()

            assert reading.value == pytest.approx(75.0, rel=0.01)
            assert reading.unit == "%"
            assert reading.sensor_id == "memory_usage"

    def test_full_memory_returns_100(self):
        meminfo = (
            "MemTotal:       4096000 kB\n"
            "MemFree:               0 kB\n"
            "MemAvailable:          0 kB\n"
        )

        with patch("pathlib.Path.read_text", return_value=meminfo):
            sensor = MemoryUsageSensor()
            reading = sensor.read()
            assert reading.value == pytest.approx(100.0)
            