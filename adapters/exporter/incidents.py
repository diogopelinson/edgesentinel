"""
O gauge de incidentes abertos, lido da loja na hora da coleta.

Um gauge de estado atual não pode ser acumulado no processo. Ele estaria
errado nas duas situações que mais importam: depois de um restart, com o
incidente ainda aberto no banco e o contador do processo em zero; e depois de
um reconhecimento feito pela CLI, que acontece em outro processo e nunca
passa por aqui. Ler a loja a cada coleta é a mesma decisão que o engine já
toma ao reler os incidentes abertos em vez de guardá-los.

Os dois exportadores compartilham count_open(): no Prometheus ele alimenta um
collector, no OTel a callback de um gauge observável. Uma segunda cópia da
contagem divergiria no dia em que um rótulo mudasse.
"""
import logging
from collections.abc import Iterable, Iterator

from prometheus_client.core import GaugeMetricFamily

from core.incidents import Incident
from core.ports import IncidentPort

logger = logging.getLogger("edgesentinel.exporter.incidents")

NAME   = "edgesentinel_incidents_open"
LABELS = ("rule", "severity", "state")

_DOC = "Incidentes abertos agora, por regra, severidade e estado"


def count_open(incidents: Iterable[Incident]) -> dict[tuple[str, str, str], int]:
    """
    Agrupa os incidentes abertos por (regra, severidade, estado).

    O estado entra como rótulo porque 'aberto e ninguém viu ainda' é a
    pergunta do operador, e uma soma sem ele não sabe respondê-la.
    """
    contagem: dict[tuple[str, str, str], int] = {}
    for incident in incidents:
        chave = (incident.rule_name, incident.severity, incident.state.value)
        contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


def read_open(incidents: IncidentPort) -> dict[tuple[str, str, str], int]:
    """
    count_open() sobre o que a loja responder agora, ou vazio se ela falhar.

    Falha não pode subir: no Prometheus ela derrubaria o scrape inteiro, e
    com ele todas as outras métricas do endpoint. Banco travado é o caso
    comum num cartão SD, e o preço de engolir está documentado — o painel
    lê zero e o motivo fica no log do agente.
    """
    try:
        return count_open(incidents.open_incidents())
    except Exception as e:
        logger.error(f"Falha ao ler incidentes abertos para as métricas: {e}")
        return {}


class OpenIncidentsCollector:
    """
    Collector do prometheus_client: publica um gauge por combinação de
    rótulos existente no momento do scrape.

    Sem incidente aberto não sai série nenhuma. É a prática esparsa do
    Prometheus — publicar zero para toda regra que já disparou deixaria
    séries mortas no banco para sempre — e obriga o painel a somar com
    'or vector(0)'.
    """

    def __init__(self, incidents: IncidentPort) -> None:
        self._incidents = incidents

    def collect(self) -> Iterator[GaugeMetricFamily]:
        familia = GaugeMetricFamily(NAME, _DOC, labels=list(LABELS))
        for rotulos, quantidade in read_open(self._incidents).items():
            familia.add_metric(list(rotulos), quantidade)
        yield familia
