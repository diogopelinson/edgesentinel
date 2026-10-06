"""
The doctor against the sensor registry.

The doctor used to keep its own list of sensors — type, module and class name,
imported by string — while _REGISTRY already maps type to class. Two lists of
the same thing: adding a sensor required editing both, and forgetting the
doctor's one made the command stop covering that sensor without anything
failing.

Silence is the worst failure mode for a diagnostic command: whoever runs the
doctor is precisely trying to find out what is not working.
"""
from adapters.sensors.registry import _REGISTRY
from cli.doctor import _check_sensors


class TestDoctorCobreTodosOsTiposRegistrados:

    def test_every_registered_type_appears_in_the_output(self, capsys):
        _check_sensors()

        saida = capsys.readouterr().out
        faltando = [tipo for tipo in _REGISTRY if tipo not in saida]

        assert faltando == [], f"o doctor não reportou: {faltando}"

    def test_it_does_not_invent_types_that_are_not_registered(self, capsys):
        """
        The other side: a hand-written list also survives the removal of a
        sensor, and the doctor starts reporting something that no longer exists.
        """
        _check_sensors()

        linhas = [
            linha for linha in capsys.readouterr().out.splitlines()
            if linha.strip() and "Sensores" not in linha
        ]
        primeiras_palavras = {
            linha.strip().split()[1] for linha in linhas if len(linha.split()) > 1
        }
        inventados = {
            p for p in primeiras_palavras
            if p.replace("_", "").isalpha() and p not in _REGISTRY
        }

        assert inventados == set()

    def test_an_unavailable_sensor_is_a_warning_not_a_failure(self, capsys):
        """
        On Windows none of the /proc sensors is available, and the doctor has
        to finish counting warnings instead of raising an exception.
        """
        erros, avisos = _check_sensors()

        assert erros == 0
        assert avisos >= 0
        assert "Sensores" in capsys.readouterr().out
