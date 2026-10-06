"""
The uptime sensor, read from /proc/uptime.

Cheap and disproportionately useful: an unexpected reboot is a drop in uptime,
and a drop in uptime is expressable as a rule with the '<' operator that
already exists. Nothing new in the engine — just a number nobody was
publishing.
"""
from unittest.mock import patch

import pytest

from adapters.sensors.base import BaseSensor
from adapters.sensors.registry import build_sensor
from adapters.sensors.uptime import UptimeSensor


def com_proc(conteudo: str):
    """Replaces the read of /proc/uptime — the test runs on any OS."""
    return patch("pathlib.Path.read_text", return_value=conteudo)


class TestLeituraDoProcUptime:

    def test_reads_the_first_field_as_seconds(self):
        """
        /proc/uptime has two fields: seconds since boot and idle seconds
        summed per CPU. The second one goes past 100% of the first on a
        machine with several cores, and is not what is wanted.
        """
        with com_proc("350735.47 234388.90\n"):
            leitura = UptimeSensor().read()

        assert leitura.value == pytest.approx(350735.47)

    def test_the_unit_is_seconds(self):
        with com_proc("100.0 50.0\n"):
            assert UptimeSensor().read().unit == "seconds"

    def test_the_default_sensor_id_is_uptime(self):
        with com_proc("100.0 50.0\n"):
            leitura = UptimeSensor().read()

        assert leitura.sensor_id == "uptime"
        assert leitura.name == "Uptime"

    def test_the_sensor_id_can_be_overridden(self):
        with com_proc("100.0 50.0\n"):
            assert UptimeSensor(sensor_id="tempo_ligado").read().sensor_id \
                == "tempo_ligado"

    def test_a_freshly_booted_device_reads_near_zero(self):
        """The case the reboot rule is looking for."""
        with com_proc("4.15 1.02\n"):
            assert UptimeSensor().read().value == pytest.approx(4.15)

    def test_extra_whitespace_does_not_break_the_parse(self):
        with com_proc("  350735.47   234388.90  \n"):
            assert UptimeSensor().read().value == pytest.approx(350735.47)

    def test_a_single_field_still_parses(self):
        """
        Two fields is what Linux writes, but depending on the second one in
        order to read the first would be coupling for no reason.
        """
        with com_proc("99.5\n"):
            assert UptimeSensor().read().value == pytest.approx(99.5)


class TestAusenciaDeProcUptime:
    """
    The availability contract: the constructor does not touch the file, and
    its absence is reported by is_available(), not by an exception at boot.
    """

    def test_constructing_does_not_touch_the_file(self):
        with patch("pathlib.Path.read_text", side_effect=AssertionError("leu no init")):
            UptimeSensor()

    def test_it_reports_itself_unavailable_without_proc_uptime(self):
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            assert UptimeSensor().is_available() is False

    def test_it_is_available_when_proc_uptime_answers(self):
        with com_proc("100.0 50.0\n"):
            assert UptimeSensor().is_available() is True

    def test_garbage_in_the_file_is_reported_as_unavailable(self):
        """
        An emulated /proc returning text is not an available sensor. The
        BaseSensor covers that: read() raises, is_available() is False.
        """
        with com_proc("nao sou um numero\n"):
            assert UptimeSensor().is_available() is False

    def test_an_empty_file_says_where_it_looked(self):
        with com_proc(""), pytest.raises(RuntimeError) as erro:
            UptimeSensor().read()

        assert "/proc/uptime" in str(erro.value)


class TestRegistro:

    def test_the_type_uptime_builds_the_sensor(self):
        sensor = build_sensor("tempo", "uptime")

        assert isinstance(sensor, UptimeSensor)
        assert isinstance(sensor, BaseSensor)
        assert sensor.sensor_id == "tempo"

    def test_it_is_listed_among_the_supported_types(self):
        with pytest.raises(ValueError) as erro:
            build_sensor("x", "nao_existe")

        assert "uptime" in str(erro.value)


class TestRegraDeReboot:
    """
    The feature's acceptance criterion: 'a drop in uptime is expressable'. It
    needed no new operator — the '<' that already existed now has something to
    compare.
    """

    def test_a_rule_fires_on_a_device_that_just_rebooted(self):
        from core.rules import Condition

        condicao = Condition(sensor_id="uptime", operator="<", threshold=300.0)

        with com_proc("42.0 10.0\n"):
            leitura = UptimeSensor().read()

        assert condicao.evaluate(leitura) is True

    def test_it_does_not_fire_on_a_device_up_for_days(self):
        from core.rules import Condition

        condicao = Condition(sensor_id="uptime", operator="<", threshold=300.0)

        with com_proc("864000.0 400000.0\n"):
            leitura = UptimeSensor().read()

        assert condicao.evaluate(leitura) is False
