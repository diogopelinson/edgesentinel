"""
The open-incidents gauge, read from the store at collection time.

A current-state gauge cannot be accumulated inside the process. It would be
wrong in the two situations that matter most: after a restart, with the
incident still open in the database and the process counter at zero; and after
an acknowledgement made from the CLI, which happens in another process and
never passes through here. Reading the store on every collection is the same
decision the engine already takes when it re-reads the open incidents instead
of keeping them.

The two exporters share count_open(): in Prometheus it feeds a collector, in
OTel the callback of an observable gauge. A second copy of the count would
diverge the day a label changed.
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
    Groups the open incidents by (rule, severity, state).

    The state goes in as a label because 'open and nobody has seen it yet' is
    the operator's question, and a sum without it cannot answer it.
    """
    contagem: dict[tuple[str, str, str], int] = {}
    for incident in incidents:
        chave = (incident.rule_name, incident.severity, incident.state.value)
        contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


def read_open(incidents: IncidentPort) -> dict[tuple[str, str, str], int]:
    """
    count_open() over whatever the store answers now, or empty if it fails.

    A failure must not propagate: in Prometheus it would bring down the whole
    scrape, and with it every other metric on the endpoint. A locked database
    is the common case on an SD card, and the price of swallowing it is
    documented — the dashboard reads zero and the reason stays in the agent's
    log.
    """
    try:
        return count_open(incidents.open_incidents())
    except Exception as e:
        logger.error(f"Falha ao ler incidentes abertos para as métricas: {e}")
        return {}


class OpenIncidentsCollector:
    """
    prometheus_client collector: publishes one gauge per label combination
    that exists at the moment of the scrape.

    With no open incident, no series comes out at all. This is Prometheus'
    sparse practice — publishing zero for every rule that has ever fired would
    leave dead series in the database forever — and it forces the dashboard to
    sum with 'or vector(0)'.
    """

    def __init__(self, incidents: IncidentPort) -> None:
        self._incidents = incidents

    def collect(self) -> Iterator[GaugeMetricFamily]:
        familia = GaugeMetricFamily(NAME, _DOC, labels=list(LABELS))
        for rotulos, quantidade in read_open(self._incidents).items():
            familia.add_metric(list(rotulos), quantidade)
        yield familia
