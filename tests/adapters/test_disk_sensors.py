"""
Disk usage and temperature.

Covers the number one cause of failure in the field — a saturated or degraded
SD card — and requires no hardware at all to be developed.

The decision these tests pin down is which percentage the sensor publishes.
`df` does not divide the used space by the device's size: it divides by what an
ordinary process can reach, because Linux reserves a slice for root. On a 1 TB
volume that slice measured 55 GB, and it is the difference between an alert
that arrives before the agent can no longer write and one that arrives after.
"""
import os
from unittest.mock import patch

import pytest

from adapters.sensors.disk_temperature import DiskTemperatureSensor
from adapters.sensors.disk_usage import DiskUsageSensor
from adapters.sensors.registry import build_sensor


class FakeStatvfs:
    """The subset of os.statvfs_result that the sensor uses."""

    def __init__(self, f_blocks: int, f_bfree: int, f_bavail: int, f_frsize: int = 4096):
        self.f_blocks = f_blocks
        self.f_bfree = f_bfree
        self.f_bavail = f_bavail
        self.f_frsize = f_frsize


def com_statvfs(resultado):
    """os.statvfs does not exist on Windows, hence the create=True."""
    return patch("os.statvfs", create=True, return_value=resultado)


# real values measured on a 1 TB volume: df reports 1%
REAL = FakeStatvfs(f_blocks=263_940_717, f_bfree=262_292_704, f_bavail=248_866_836)


class TestPercentualDeUso:

    def test_it_reports_what_df_reports(self):
        """
        df: used / (used + available), not used / total size. The calculation
        over the total size would give 0.62% on these numbers, and df shows 1%.
        """
        with com_statvfs(REAL):
            assert DiskUsageSensor().read().value == pytest.approx(0.66, abs=0.01)

    def test_a_full_filesystem_reads_one_hundred(self):
        """
        The point at which the agent can no longer write is f_bavail zero, and
        that is where the number has to reach 100 — not at f_blocks exhausted.
        """
        cheio = FakeStatvfs(f_blocks=1000, f_bfree=50, f_bavail=0)

        with com_statvfs(cheio):
            assert DiskUsageSensor().read().value == pytest.approx(100.0)

    def test_the_root_reserve_is_not_counted_as_free(self):
        """
        With f_bfree > f_bavail there is space only root can reach. Counting it
        as free would delay the alert right at the end, where it matters.
        """
        reservado = FakeStatvfs(f_blocks=1000, f_bfree=100, f_bavail=50)

        with com_statvfs(reservado):
            valor = DiskUsageSensor().read().value

        # used=900, available=50 -> 900/950
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
        Two disk sensors on the same dashboard are indistinguishable if the
        name does not say which filesystem each one measures.
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
    A mountpoint that does not exist is absent hardware, not a config error: a
    card that failed to mount at boot must not bring the agent down.
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
        f_blocks zero is a pseudo-filesystem, not a disk at 0%. Dividing by it
        would be a ZeroDivisionError on the read.
        """
        with com_statvfs(FakeStatvfs(f_blocks=0, f_bfree=0, f_bavail=0)):
            assert DiskUsageSensor().is_available() is False


# --- temperature ---

class TestTemperaturaDeDisco:
    """
    Read from /sys/class/hwmon, where the kernel publishes each sensor chip
    with a name. The disk's one is 'drivetemp' (SATA, via the module of the
    same name) or 'nvme'.
    """

    def escreve_hwmon(self, tmp_path, nomes: dict[str, str]):
        """Builds a fake hwmon tree: {chip_name: contents_of_temp1_input}."""
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
        hwmon publishes everything — CPU, motherboard, fans. Taking the first
        chip would give the temperature of something else, at a plausible value.
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
        The common case: most machines do not load the drivetemp module, and
        that is absent hardware, not an error.
        """
        raiz = self.escreve_hwmon(tmp_path, {"coretemp": "78000"})

        assert DiskTemperatureSensor(hwmon_root=str(raiz)).is_available() is False

    def test_a_missing_hwmon_directory_reports_unavailable(self, tmp_path):
        ausente = tmp_path / "nao_existe"

        assert DiskTemperatureSensor(hwmon_root=str(ausente)).is_available() is False

    def test_a_missing_hwmon_directory_still_explains_itself(self, tmp_path):
        """
        Found by mutation: is_available() returns False with or without the
        missing-directory guard, so it alone does not justify the guard. What
        justifies it is the message — without the guard, read() raises
        FileNotFoundError on a path, and with it the message says what it
        looked for and that on SATA this requires a loaded module. Whoever
        reads the log is the one who pays the difference.
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
        Not every hwmon chip publishes temp1_input. Assuming it does would give
        a FileNotFoundError on a read that should just skip that chip.
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
    Documents why the tests use create=True: on Windows the attribute does not
    exist, and that is why the sensor declares itself unavailable there.
    """
    if os.name == "nt":
        assert not hasattr(os, "statvfs")
