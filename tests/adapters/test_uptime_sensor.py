"""
O sensor de uptime, lido de /proc/uptime.

Barato e desproporcionalmente útil: um reboot inesperado é uma queda de
uptime, e queda de uptime é expressável como regra com o operador '<' que já
existe. Nada de novo no motor — só um número que ninguém estava publicando.
"""
from unittest.mock import patch

import pytest

from adapters.sensors.base import BaseSensor
from adapters.sensors.registry import build_sensor
from adapters.sensors.uptime import UptimeSensor


def com_proc(conteudo: str):
    """Substitui a leitura de /proc/uptime — o teste roda em qualquer SO."""
    return patch("pathlib.Path.read_text", return_value=conteudo)


class TestLeituraDoProcUptime:

    def test_reads_the_first_field_as_seconds(self):
        """
        /proc/uptime tem dois campos: segundos desde o boot e segundos
        ociosos somados por CPU. O segundo passa de 100% do primeiro numa
        máquina com vários núcleos, e não é o que se quer.
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
        """O caso que a regra de reboot procura."""
        with com_proc("4.15 1.02\n"):
            assert UptimeSensor().read().value == pytest.approx(4.15)

    def test_extra_whitespace_does_not_break_the_parse(self):
        with com_proc("  350735.47   234388.90  \n"):
            assert UptimeSensor().read().value == pytest.approx(350735.47)

    def test_a_single_field_still_parses(self):
        """
        Dois campos é o que o Linux escreve, mas depender do segundo para ler
        o primeiro seria acoplamento sem motivo.
        """
        with com_proc("99.5\n"):
            assert UptimeSensor().read().value == pytest.approx(99.5)


class TestAusenciaDeProcUptime:
    """
    O contrato de disponibilidade: o construtor não toca o arquivo, e a
    ausência é informada por is_available(), não por exceção no boot.
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
        Um /proc emulado devolvendo texto não é um sensor disponível. O
        BaseSensor cobre isso: read() levanta, is_available() é False.
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
    A aceitação da feature: 'queda de uptime é expressável'. Não precisou de
    operador novo — o '<' que já existia passa a ter o que comparar.
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
