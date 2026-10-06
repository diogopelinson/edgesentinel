"""
Per-sensor params in the YAML, passed on to the class's constructor.

The bottleneck this solves: today build_sensor() calls cls(sensor_id=...) and
nothing else, so any sensor that needs a pin, an I2C address or a mountpoint
requires touching config/schema.py. With free-form params, each class's
signature becomes the declaration of what it accepts.

The decision these tests pin down: the params are validated against the
signature **before** constructing. Calling and catching TypeError would be
shorter and would mix two different errors — 'this sensor does not accept this
param' and 'the sensor's constructor broke' —, and the second must not turn
into a message about config.
"""
import pytest

from adapters.sensors.base import BaseSensor
from adapters.sensors.registry import build_sensor
from core.entities import SensorReading


# --- test doubles ---

class SensorComParams(BaseSensor):
    """A test sensor that declares in its signature what it accepts."""

    construido = 0

    def __init__(
        self,
        sensor_id: str = "teste",
        pino: int = 4,
        escala: float = 1.0,
        rotulo: str = "padrão",
        invertido: bool = False,
    ) -> None:
        super().__init__(sensor_id=sensor_id, name="Teste", unit="u")
        SensorComParams.construido += 1
        self.pino = pino
        self.escala = escala
        self.rotulo = rotulo
        self.invertido = invertido

    def read(self) -> SensorReading:
        return self._build_reading(self.pino * self.escala)


class SensorQueAceitaTudo(BaseSensor):
    """**kwargs in the signature means 'I accept any param'."""

    def __init__(self, sensor_id: str = "tudo", **extras: object) -> None:
        super().__init__(sensor_id=sensor_id, name="Tudo", unit="u")
        self.extras = extras

    def read(self) -> SensorReading:
        return self._build_reading(0.0)


class SensorQuebrado(BaseSensor):
    """The TypeError comes from inside the constructor, not from the signature."""

    def __init__(self, sensor_id: str = "quebrado", fator: int = 1) -> None:
        super().__init__(sensor_id=sensor_id, name="Quebrado", unit="u")
        raise TypeError("nao da para somar str com int aqui dentro")

    def read(self) -> SensorReading:
        return self._build_reading(0.0)


@pytest.fixture
def registra(monkeypatch):
    """Registers the test doubles without touching the real map of types."""
    from adapters.sensors import registry

    tipos = dict(registry._REGISTRY)
    tipos.update({
        "com_params": SensorComParams,
        "aceita_tudo": SensorQueAceitaTudo,
        "quebrado": SensorQuebrado,
    })
    monkeypatch.setattr(registry, "_REGISTRY", tipos)
    SensorComParams.construido = 0


# --- what already existed stays the same ---

class TestSensoresSemParams:

    @pytest.mark.parametrize("tipo", ["cpu_temperature", "cpu_usage", "memory_usage"])
    def test_the_three_existing_sensors_build_with_no_params(self, tipo):
        sensor = build_sensor("qualquer", tipo)

        assert isinstance(sensor, BaseSensor)
        assert sensor.sensor_id == "qualquer"

    def test_an_empty_params_dict_is_the_same_as_none(self):
        assert build_sensor("x", "cpu_usage", {}).sensor_id == "x"

    def test_an_unknown_type_still_raises_naming_the_supported_ones(self):
        with pytest.raises(ValueError) as erro:
            build_sensor("x", "nao_existe")

        assert "nao_existe" in str(erro.value)
        assert "cpu_usage" in str(erro.value)


# --- the params reaching the constructor ---

class TestParamsChegamAoConstrutor:

    def test_params_reach_the_constructor(self, registra):
        sensor = build_sensor("s1", "com_params", {"pino": 17})

        assert sensor.pino == 17

    def test_the_types_survive_as_written(self, registra):
        sensor = build_sensor("s1", "com_params", {
            "pino": 17, "escala": 0.5, "rotulo": "porta", "invertido": True,
        })

        assert sensor.pino == 17
        assert sensor.escala == 0.5
        assert sensor.rotulo == "porta"
        assert sensor.invertido is True

    def test_omitted_params_keep_the_constructor_defaults(self, registra):
        sensor = build_sensor("s1", "com_params", {"pino": 9})

        assert sensor.escala == 1.0
        assert sensor.rotulo == "padrão"

    def test_the_sensor_id_still_comes_from_the_id_field(self, registra):
        assert build_sensor("nome_do_yaml", "com_params", {"pino": 1}).sensor_id \
            == "nome_do_yaml"

    def test_a_var_keyword_signature_accepts_anything(self, registra):
        sensor = build_sensor("s1", "aceita_tudo", {"seja_o_que_for": 42})

        assert sensor.extras == {"seja_o_que_for": 42}


# --- the wrong param, at boot ---

class TestParamDesconhecido:

    def test_an_unknown_param_raises_naming_the_sensor_and_the_param(self, registra):
        with pytest.raises(ValueError) as erro:
            build_sensor("porta_da_estufa", "com_params", {"pinos": 17})

        mensagem = str(erro.value)
        assert "porta_da_estufa" in mensagem
        assert "com_params" in mensagem
        assert "pinos" in mensagem

    def test_the_message_lists_what_the_sensor_does_accept(self, registra):
        with pytest.raises(ValueError) as erro:
            build_sensor("s1", "com_params", {"pinos": 17})

        mensagem = str(erro.value)
        for aceito in ("pino", "escala", "rotulo", "invertido"):
            assert aceito in mensagem

    def test_the_message_does_not_offer_sensor_id_as_a_param(self, registra):
        """
        sensor_id is in the signature but comes from the `id:` field. Listing
        it among the accepted params would invite declaring it twice.
        """
        with pytest.raises(ValueError) as erro:
            build_sensor("s1", "com_params", {"pinos": 17})

        assert "sensor_id" not in str(erro.value)

    def test_it_fails_before_constructing(self, registra):
        """
        Validating before calling is the whole point. If the validation were a
        try/except around cls(...), a sensor with a side effect in __init__ —
        opening an I2C bus, taking a pin — would already have done it by the
        time the error showed up.
        """
        with pytest.raises(ValueError):
            build_sensor("s1", "com_params", {"pinos": 17})

        assert SensorComParams.construido == 0

    def test_every_unknown_param_is_named_at_once(self, registra):
        """
        One per boot round would make the operator find the errors one by one.
        """
        with pytest.raises(ValueError) as erro:
            build_sensor("s1", "com_params", {"pinos": 1, "escalar": 2})

        mensagem = str(erro.value)
        assert "pinos" in mensagem
        assert "escalar" in mensagem

    def test_sensor_id_inside_params_is_refused_with_its_own_message(self, registra):
        """
        It would come through as a duplicate keyword argument, in a TypeError
        that explains nothing. The sensor's id has one place in the YAML, and
        it is `id:`.
        """
        with pytest.raises(ValueError) as erro:
            build_sensor("s1", "com_params", {"sensor_id": "outro"})

        mensagem = str(erro.value)
        assert "sensor_id" in mensagem
        assert "id" in mensagem

    def test_a_type_error_from_inside_the_constructor_is_not_disguised(self, registra):
        """
        Catching TypeError around the construction would turn a bug in the
        sensor into a message about config, and the operator would go and
        fiddle with the YAML.
        """
        with pytest.raises(TypeError) as erro:
            build_sensor("s1", "quebrado", {"fator": 2})

        assert "aqui dentro" in str(erro.value)


class TestOBuilderRepassaOsParams:
    """
    Found by mutation: deleting the params from the call in cli/builder.py left
    all 250 tests green. The path from the YAML to the constructor has two
    bridges — the loader and the builder — and testing only the registry covers
    one of them.
    """

    def test_the_builder_hands_the_params_to_the_sensor(self, registra):
        from cli.builder import _build_sensors
        from config.schema import EdgeSentinelConfig, SensorConfig

        config = EdgeSentinelConfig(
            sensors=[SensorConfig(
                id="estufa", type="com_params", params={"pino": 23, "escala": 2.0},
            )],
            rules=[],
            actions=[],
        )

        (sensor,) = _build_sensors(config)

        assert sensor.pino == 23
        assert sensor.escala == 2.0

    def test_a_bad_param_stops_that_sensor_and_not_the_boot(self, registra, caplog):
        """
        The builder already treats a construction failure as an ERROR and
        carries on with the other sensors. A wrong param goes down that same
        path: one badly declared sensor must not bring the whole agent down.
        """
        import logging

        from cli.builder import _build_sensors
        from config.schema import EdgeSentinelConfig, SensorConfig

        config = EdgeSentinelConfig(
            sensors=[
                SensorConfig(id="ruim", type="com_params", params={"pinos": 1}),
                SensorConfig(id="bom", type="com_params", params={"pino": 4}),
            ],
            rules=[],
            actions=[],
        )

        with caplog.at_level(logging.ERROR, logger="edgesentinel.builder"):
            sensores = _build_sensors(config)

        assert [s.sensor_id for s in sensores] == ["bom"]
        assert "ruim" in caplog.text
        assert "pinos" in caplog.text
