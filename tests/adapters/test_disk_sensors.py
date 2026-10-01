"""
Uso e temperatura de disco.

Cobre a causa número um de falha em campo — cartão SD saturado ou degradado —
e não exige hardware nenhum para ser desenvolvido.

A decisão que estes testes fixam é qual percentual o sensor publica. `df` não
divide o usado pelo tamanho do dispositivo: ele divide pelo que um processo
comum pode alcançar, porque o Linux reserva uma fatia para o root. Num volume
de 1 TB essa fatia foram 55 GB medidos, e é a diferença entre um alerta que
chega antes de o agente não conseguir mais escrever e um que chega depois.
"""
import os
from unittest.mock import patch

import pytest

from adapters.sensors.disk_temperature import DiskTemperatureSensor
from adapters.sensors.disk_usage import DiskUsageSensor
from adapters.sensors.registry import build_sensor


class FakeStatvfs:
    """O subconjunto de os.statvfs_result que o sensor usa."""

    def __init__(self, f_blocks: int, f_bfree: int, f_bavail: int, f_frsize: int = 4096):
        self.f_blocks = f_blocks
        self.f_bfree = f_bfree
        self.f_bavail = f_bavail
        self.f_frsize = f_frsize


def com_statvfs(resultado):
    """os.statvfs não existe no Windows, daí o create=True."""
    return patch("os.statvfs", create=True, return_value=resultado)


# valores reais medidos num volume de 1 TB: df reporta 1%
REAL = FakeStatvfs(f_blocks=263_940_717, f_bfree=262_292_704, f_bavail=248_866_836)


class TestPercentualDeUso:

    def test_it_reports_what_df_reports(self):
        """
        df: usado / (usado + disponível), não usado / tamanho total. A conta
        sobre o tamanho total daria 0.62% nestes números, e o df mostra 1%.
        """
        with com_statvfs(REAL):
            assert DiskUsageSensor().read().value == pytest.approx(0.66, abs=0.01)

    def test_a_full_filesystem_reads_one_hundred(self):
        """
        O ponto em que o agente deixa de conseguir escrever é f_bavail zero, e
        é ali que o número tem de chegar a 100 — não em f_blocks esgotado.
        """
        cheio = FakeStatvfs(f_blocks=1000, f_bfree=50, f_bavail=0)

        with com_statvfs(cheio):
            assert DiskUsageSensor().read().value == pytest.approx(100.0)

    def test_the_root_reserve_is_not_counted_as_free(self):
        """
        Com f_bfree > f_bavail há espaço que só o root alcança. Contá-lo como
        livre atrasaria o alerta justamente no fim, onde ele importa.
        """
        reservado = FakeStatvfs(f_blocks=1000, f_bfree=100, f_bavail=50)

        with com_statvfs(reservado):
            valor = DiskUsageSensor().read().value

        # usado=900, disponivel=50 -> 900/950
        assert valor == pytest.approx(94.74, abs=0.01)

    def test_an_empty_filesystem_reads_zero(self):
        vazio = FakeStatvfs(f_blocks=1000, f_bfree=1000, f_bavail=1000)

        with com_statvfs(vazio):
            assert DiskUsageSensor().read().value == pytest.approx(0.0)

    def test_the_unit_is_percent(self):
        with com_statvfs(REAL):
            assert DiskUsageSensor().read().unit == "%"

    def test_the_value_stays_inside_zero_and_one_hundred(self):
        with com_statvfs(REAL):
            valor = DiskUsageSensor().read().value

        assert 0.0 <= valor <= 100.0


class TestMountpoint:

    def test_the_default_mountpoint_is_root(self):
        with com_statvfs(REAL) as statvfs:
            DiskUsageSensor().read()

        statvfs.assert_called_once_with("/")

    def test_the_mountpoint_comes_from_params(self):
        with com_statvfs(REAL) as statvfs:
            DiskUsageSensor(mountpoint="/var/log").read()

        statvfs.assert_called_once_with("/var/log")

    def test_the_mountpoint_is_visible_in_the_name(self):
        """
        Dois sensores de disco no mesmo painel são indistinguíveis se o nome
        não disser qual sistema de arquivos cada um mede.
        """
        with com_statvfs(REAL):
            assert "/var/log" in DiskUsageSensor(mountpoint="/var/log").read().name

    def test_it_reaches_the_sensor_through_the_registry(self):
        sensor = build_sensor("disco_log", "disk_usage", {"mountpoint": "/var/log"})

        with com_statvfs(REAL) as statvfs:
            sensor.read()

        statvfs.assert_called_once_with("/var/log")

    def test_an_unknown_param_is_refused_naming_the_sensor(self):
        with pytest.raises(ValueError) as erro:
            build_sensor("disco", "disk_usage", {"ponto": "/var"})

        mensagem = str(erro.value)
        assert "disco" in mensagem
        assert "ponto" in mensagem
        assert "mountpoint" in mensagem


class TestMountpointAusente:
    """
    Ponto de montagem que não existe é hardware ausente, não erro de config: um
    cartão que não montou no boot não pode derrubar o agente.
    """

    def test_constructing_does_not_touch_the_filesystem(self):
        with patch("os.statvfs", create=True, side_effect=AssertionError("leu no init")):
            DiskUsageSensor(mountpoint="/nao/existe")

    def test_a_missing_mountpoint_reports_unavailable(self):
        with patch("os.statvfs", create=True, side_effect=FileNotFoundError):
            assert DiskUsageSensor(mountpoint="/nao/existe").is_available() is False

    def test_it_is_available_when_the_mountpoint_answers(self):
        with com_statvfs(REAL):
            assert DiskUsageSensor().is_available() is True

    def test_a_filesystem_reporting_no_blocks_is_unavailable(self):
        """
        f_blocks zero é um pseudo-sistema de arquivos, não um disco de 0%.
        Dividir por ele seria ZeroDivisionError na leitura.
        """
        with com_statvfs(FakeStatvfs(f_blocks=0, f_bfree=0, f_bavail=0)):
            assert DiskUsageSensor().is_available() is False


# --- temperatura ---

class TestTemperaturaDeDisco:
    """
    Lida de /sys/class/hwmon, onde o kernel publica cada chip de sensor com um
    nome. O do disco é 'drivetemp' (SATA, via o módulo de mesmo nome) ou 'nvme'.
    """

    def escreve_hwmon(self, tmp_path, nomes: dict[str, str]):
        """Monta uma árvore hwmon falsa: {nome_do_chip: conteudo_de_temp1_input}."""
        raiz = tmp_path / "hwmon"
        raiz.mkdir()
        for i, (nome, temp) in enumerate(nomes.items()):
            d = raiz / f"hwmon{i}"
            d.mkdir()
            (d / "name").write_text(f"{nome}\n", encoding="utf-8")
            (d / "temp1_input").write_text(f"{temp}\n", encoding="utf-8")
        return raiz

    def test_it_reads_drivetemp_in_millidegrees(self, tmp_path):
        raiz = self.escreve_hwmon(tmp_path, {"drivetemp": "41000"})

        leitura = DiskTemperatureSensor(hwmon_root=str(raiz)).read()

        assert leitura.value == pytest.approx(41.0)
        assert leitura.unit == "°C"

    def test_it_reads_nvme_too(self, tmp_path):
        raiz = self.escreve_hwmon(tmp_path, {"nvme": "38500"})

        assert DiskTemperatureSensor(hwmon_root=str(raiz)).read().value \
            == pytest.approx(38.5)

    def test_it_skips_chips_that_are_not_disks(self, tmp_path):
        """
        hwmon publica de tudo — CPU, placa-mãe, ventoinha. Pegar o primeiro
        chip daria a temperatura de outra coisa, num valor plausível.
        """
        raiz = self.escreve_hwmon(tmp_path, {
            "coretemp": "78000", "acpitz": "55000", "drivetemp": "41000",
        })

        assert DiskTemperatureSensor(hwmon_root=str(raiz)).read().value \
            == pytest.approx(41.0)

    def test_a_named_chip_from_params_wins(self, tmp_path):
        raiz = self.escreve_hwmon(tmp_path, {"drivetemp": "41000", "nvme": "38500"})

        assert DiskTemperatureSensor(
            hwmon_root=str(raiz), chip="nvme",
        ).read().value == pytest.approx(38.5)

    def test_a_named_chip_that_is_absent_says_what_it_looked_for(self, tmp_path):
        raiz = self.escreve_hwmon(tmp_path, {"drivetemp": "41000"})

        with pytest.raises(RuntimeError) as erro:
            DiskTemperatureSensor(hwmon_root=str(raiz), chip="nvme").read()

        assert "nvme" in str(erro.value)

    def test_no_disk_chip_at_all_reports_unavailable(self, tmp_path):
        """
        O caso comum: a maioria das máquinas não carrega o módulo drivetemp, e
        isso é ausência de hardware, não erro.
        """
        raiz = self.escreve_hwmon(tmp_path, {"coretemp": "78000"})

        assert DiskTemperatureSensor(hwmon_root=str(raiz)).is_available() is False

    def test_a_missing_hwmon_directory_reports_unavailable(self, tmp_path):
        ausente = tmp_path / "nao_existe"

        assert DiskTemperatureSensor(hwmon_root=str(ausente)).is_available() is False

    def test_a_missing_hwmon_directory_still_explains_itself(self, tmp_path):
        """
        Achado por mutação: is_available() devolve False com ou sem a guarda de
        diretório ausente, então só ela não justifica a guarda. O que justifica
        é a mensagem — sem a guarda, read() levanta FileNotFoundError num
        caminho, e com ela diz o que procurou e que em SATA isso exige um
        módulo carregado. Quem lê o log é quem paga a diferença.
        """
        ausente = tmp_path / "nao_existe"

        with pytest.raises(RuntimeError) as erro:
            DiskTemperatureSensor(hwmon_root=str(ausente)).read()

        mensagem = str(erro.value)
        assert str(ausente) in mensagem
        assert "drivetemp" in mensagem

    def test_the_error_names_the_directory_it_searched(self, tmp_path):
        raiz = self.escreve_hwmon(tmp_path, {"coretemp": "78000"})

        with pytest.raises(RuntimeError) as erro:
            DiskTemperatureSensor(hwmon_root=str(raiz)).read()

        assert str(raiz) in str(erro.value)

    def test_a_chip_without_temp1_input_is_skipped(self, tmp_path):
        """
        Nem todo chip hwmon publica temp1_input. Assumir que sim daria
        FileNotFoundError numa leitura que deveria só pular aquele chip.
        """
        raiz = self.escreve_hwmon(tmp_path, {"drivetemp": "41000"})
        (raiz / "hwmon0" / "temp1_input").unlink()
        d = raiz / "hwmon1"
        d.mkdir()
        (d / "name").write_text("nvme\n", encoding="utf-8")
        (d / "temp1_input").write_text("38500\n", encoding="utf-8")

        assert DiskTemperatureSensor(hwmon_root=str(raiz)).read().value \
            == pytest.approx(38.5)

    def test_constructing_does_not_touch_the_filesystem(self, tmp_path):
        with patch("pathlib.Path.iterdir", side_effect=AssertionError("leu no init")):
            DiskTemperatureSensor(hwmon_root=str(tmp_path))


class TestRegistro:

    @pytest.mark.parametrize("tipo", ["disk_usage", "disk_temperature"])
    def test_both_types_are_registered(self, tipo):
        assert build_sensor("d", tipo).sensor_id == "d"

    def test_they_are_listed_among_the_supported_types(self):
        with pytest.raises(ValueError) as erro:
            build_sensor("x", "nao_existe")

        mensagem = str(erro.value)
        assert "disk_usage" in mensagem
        assert "disk_temperature" in mensagem


class TestRegraDeDiscoCheio:

    def test_a_rule_fires_on_a_saturated_card(self):
        from core.rules import Condition

        condicao = Condition(sensor_id="disk", operator=">", threshold=90.0)
        cheio = FakeStatvfs(f_blocks=1000, f_bfree=60, f_bavail=50)

        with com_statvfs(cheio):
            leitura = DiskUsageSensor(sensor_id="disk").read()

        assert condicao.evaluate(leitura) is True


def test_os_statvfs_is_unix_only():
    """
    Documenta por que os testes usam create=True: no Windows o atributo não
    existe, e é por isso que o sensor se declara indisponível lá.
    """
    if os.name == "nt":
        assert not hasattr(os, "statvfs")
