"""
O doctor contra o registry de sensores.

O doctor mantinha a própria lista de sensores — type, módulo e nome de classe,
importados por string — enquanto o _REGISTRY já mapeia type para classe. Duas
listas da mesma coisa: acrescentar um sensor exigia editar as duas, e esquecer
a do doctor fazia o comando parar de cobrir aquele sensor sem nada falhar.

Silêncio é o pior modo de falha para um comando de diagnóstico: quem roda o
doctor está justamente tentando descobrir o que não está funcionando.
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
        O outro lado: uma lista à mão também sobrevive à remoção de um sensor,
        e o doctor passa a reportar algo que não existe mais.
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
        No Windows nenhum dos sensores de /proc está disponível, e o doctor
        tem de terminar contando avisos em vez de levantar exceção.
        """
        erros, avisos = _check_sensors()

        assert erros == 0
        assert avisos >= 0
        assert "Sensores" in capsys.readouterr().out
