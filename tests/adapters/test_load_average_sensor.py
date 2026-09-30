"""
O sensor de load average, lido de /proc/loadavg.

O que ele acrescenta ao motor de regras é a janela temporal que o cpu_usage
instantâneo não tem: 100% de CPU num instante é uma leitura, load 4 sustentado
por quinze minutos num dispositivo de um núcleo é um problema.

É também o primeiro sensor a usar o bloco `params` de verdade, e a divisão de
responsabilidade que estes testes fixam: o registry confere o **nome** dos
params contra a assinatura, e o construtor confere o **valor**.
"""
from unittest.mock import patch

import pytest

from adapters.sensors.load_average import LoadAverageSensor
from adapters.sensors.registry import build_sensor

# 1min 5min 15min  procs_rodando/total  ultimo_pid
LOADAVG = "0.42 1.15 2.30 2/431 12345\n"


def com_proc(conteudo: str = LOADAVG):
    return patch("pathlib.Path.read_text", return_value=conteudo)


class TestAsTresJanelas:

    def test_the_default_window_is_one_minute(self):
        with com_proc():
            assert LoadAverageSensor().read().value == pytest.approx(0.42)

    @pytest.mark.parametrize(("janela", "esperado"), [(1, 0.42), (5, 1.15), (15, 2.30)])
    def test_each_window_reads_its_own_column(self, janela, esperado):
        with com_proc():
            assert LoadAverageSensor(window=janela).read().value == pytest.approx(esperado)

    def test_the_window_is_visible_in_the_name(self):
        """
        Três sensores de load no mesmo painel são indistinguíveis se o nome
        não disser qual janela cada um lê.
        """
        with com_proc():
            assert "15" in LoadAverageSensor(window=15).read().name

    def test_the_trailing_process_fields_are_ignored(self):
        """
        /proc/loadavg tem cinco campos e só os três primeiros são load. Ler
        pela posição do fim pegaria o último pid.
        """
        with com_proc():
            leitura = LoadAverageSensor(window=15).read()

        assert leitura.value == pytest.approx(2.30)
        assert leitura.value != 12345


class TestJanelaInvalida:
    """
    O valor é checado no construtor, não no registry: o registry confere que
    'window' é um param que este sensor aceita, e só o sensor sabe que 7 não é
    uma janela que o Linux publica.
    """

    @pytest.mark.parametrize("janela", [0, 2, 7, 60, -1])
    def test_a_window_the_kernel_does_not_publish_is_refused(self, janela):
        with pytest.raises(ValueError) as erro:
            LoadAverageSensor(window=janela)

        assert "window" in str(erro.value)

    def test_the_message_says_which_windows_exist(self):
        with pytest.raises(ValueError) as erro:
            LoadAverageSensor(window=7)

        mensagem = str(erro.value)
        assert "7" in mensagem
        for valida in ("1", "5", "15"):
            assert valida in mensagem

    def test_a_string_window_is_refused_too(self):
        """
        `window: "5"` no YAML chega como str. Aceitar calado faria o sensor ler
        a janela errada ou explodir mais tarde no índice.
        """
        with pytest.raises(ValueError):
            LoadAverageSensor(window="5")

    def test_it_fails_when_constructed_not_when_read(self):
        """
        Config errado é erro de boot. Descobrir isso na primeira leitura
        deixaria o agente subir sem o sensor e sem dizer por quê.
        """
        with pytest.raises(ValueError):
            LoadAverageSensor(window=7)


class TestParamNaoReconhecido:

    def test_an_unknown_param_is_refused_by_the_registry(self):
        """
        A outra metade da divisão: o nome do param é problema do registry, e a
        mensagem dele nomeia o sensor do YAML.
        """
        with pytest.raises(ValueError) as erro:
            build_sensor("carga", "load_average", {"janela": 5})

        mensagem = str(erro.value)
        assert "carga" in mensagem
        assert "janela" in mensagem
        assert "window" in mensagem

    def test_the_window_param_reaches_the_sensor_through_the_registry(self):
        sensor = build_sensor("carga", "load_average", {"window": 15})

        with com_proc():
            assert sensor.read().value == pytest.approx(2.30)


class TestAusenciaDeProcLoadavg:

    def test_constructing_does_not_touch_the_file(self):
        with patch("pathlib.Path.read_text", side_effect=AssertionError("leu no init")):
            LoadAverageSensor()

    def test_it_reports_itself_unavailable_without_the_file(self):
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            assert LoadAverageSensor().is_available() is False

    def test_it_is_available_when_the_file_answers(self):
        with com_proc():
            assert LoadAverageSensor().is_available() is True

    def test_a_short_file_says_where_it_looked(self):
        with com_proc("0.42\n"), pytest.raises(RuntimeError) as erro:
            LoadAverageSensor(window=15).read()

        assert "/proc/loadavg" in str(erro.value)


class TestRegistro:

    def test_the_type_load_average_builds_the_sensor(self):
        sensor = build_sensor("carga", "load_average")

        assert isinstance(sensor, LoadAverageSensor)
        assert sensor.sensor_id == "carga"

    def test_the_unit_is_the_same_for_every_window(self):
        with com_proc():
            unidades = {LoadAverageSensor(window=j).read().unit for j in (1, 5, 15)}

        assert len(unidades) == 1
