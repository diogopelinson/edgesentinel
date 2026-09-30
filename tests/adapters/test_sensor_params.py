"""
Params por sensor no YAML, repassados ao construtor da classe.

O gargalo que isto resolve: hoje build_sensor() chama cls(sensor_id=...) e
nada mais, então qualquer sensor que precise de um pino, um endereço I2C ou um
mountpoint exige mexer em config/schema.py. Com params livres, a assinatura de
cada classe passa a ser a declaração do que ela aceita.

A decisão que estes testes fixam: os params são validados contra a assinatura
**antes** de construir. Chamar e capturar TypeError seria mais curto e
misturaria dois erros diferentes — 'esse sensor não aceita esse param' e 'o
construtor do sensor quebrou' —, e o segundo não deve virar mensagem sobre
config.
"""
import pytest

from adapters.sensors.base import BaseSensor
from adapters.sensors.registry import build_sensor
from core.entities import SensorReading


# --- dublês ---

class SensorComParams(BaseSensor):
    """Sensor de teste que declara na assinatura o que aceita."""

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
    """**kwargs na assinatura significa 'aceito qualquer param'."""

    def __init__(self, sensor_id: str = "tudo", **extras: object) -> None:
        super().__init__(sensor_id=sensor_id, name="Tudo", unit="u")
        self.extras = extras

    def read(self) -> SensorReading:
        return self._build_reading(0.0)


class SensorQuebrado(BaseSensor):
    """O TypeError vem de dentro do construtor, não da assinatura."""

    def __init__(self, sensor_id: str = "quebrado", fator: int = 1) -> None:
        super().__init__(sensor_id=sensor_id, name="Quebrado", unit="u")
        raise TypeError("nao da para somar str com int aqui dentro")

    def read(self) -> SensorReading:
        return self._build_reading(0.0)


@pytest.fixture
def registra(monkeypatch):
    """Registra os dublês sem tocar no mapa real de tipos."""
    from adapters.sensors import registry

    tipos = dict(registry._REGISTRY)
    tipos.update({
        "com_params": SensorComParams,
        "aceita_tudo": SensorQueAceitaTudo,
        "quebrado": SensorQuebrado,
    })
    monkeypatch.setattr(registry, "_REGISTRY", tipos)
    SensorComParams.construido = 0


# --- o que já existia continua igual ---

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


# --- os params chegando ao construtor ---

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


# --- o param errado, no boot ---

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
        sensor_id está na assinatura mas vem do campo `id:`. Listá-lo entre os
        params aceitos convidaria a declará-lo duas vezes.
        """
        with pytest.raises(ValueError) as erro:
            build_sensor("s1", "com_params", {"pinos": 17})

        assert "sensor_id" not in str(erro.value)

    def test_it_fails_before_constructing(self, registra):
        """
        Validar antes de chamar é o ponto. Se a validação fosse um try/except
        em volta de cls(...), um sensor com efeito colateral no __init__ — abrir
        um barramento I2C, tomar um pino — já o teria feito quando o erro
        aparecesse.
        """
        with pytest.raises(ValueError):
            build_sensor("s1", "com_params", {"pinos": 17})

        assert SensorComParams.construido == 0

    def test_every_unknown_param_is_named_at_once(self, registra):
        """
        Um por rodada de boot faria o operador descobrir os erros de um em um.
        """
        with pytest.raises(ValueError) as erro:
            build_sensor("s1", "com_params", {"pinos": 1, "escalar": 2})

        mensagem = str(erro.value)
        assert "pinos" in mensagem
        assert "escalar" in mensagem

    def test_sensor_id_inside_params_is_refused_with_its_own_message(self, registra):
        """
        Passaria como duplicate keyword argument, num TypeError que não explica
        nada. O id do sensor tem um lugar no YAML e é `id:`.
        """
        with pytest.raises(ValueError) as erro:
            build_sensor("s1", "com_params", {"sensor_id": "outro"})

        mensagem = str(erro.value)
        assert "sensor_id" in mensagem
        assert "id" in mensagem

    def test_a_type_error_from_inside_the_constructor_is_not_disguised(self, registra):
        """
        Capturar TypeError em volta da construção transformaria um bug do
        sensor em mensagem sobre config, e o operador iria mexer no YAML.
        """
        with pytest.raises(TypeError) as erro:
            build_sensor("s1", "quebrado", {"fator": 2})

        assert "aqui dentro" in str(erro.value)
