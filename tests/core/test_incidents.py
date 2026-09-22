import dataclasses
import time

import pytest

from core.incidents import Incident, IncidentState


def make_incident(**overrides) -> Incident:
    fields = dict(
        rule_name="alta_temperatura",
        sensor_id="cpu_temp",
        severity="warning",
    )
    fields.update(overrides)
    return Incident(**fields)


class TestIncidentState:

    def test_has_the_three_stored_states(self):
        """
        NORMAL não é guardado: o normal é a ausência de incidente aberto.
        Guardá-lo criaria uma linha por regra que nunca disparou.
        """
        assert [s.value for s in IncidentState] == ["triggered", "acknowledged", "resolved"]

    def test_compares_equal_to_its_string_value(self):
        """str Enum, como Severity — atravessa o SQLite sem conversão."""
        assert IncidentState.TRIGGERED == "triggered"


class TestIncident:

    def test_is_immutable(self):
        incident = make_incident()

        with pytest.raises(dataclasses.FrozenInstanceError):
            incident.state = IncidentState.RESOLVED

    def test_opens_triggered(self):
        assert make_incident().state is IncidentState.TRIGGERED

    def test_opened_at_defaults_to_now(self):
        before = time.time()
        incident = make_incident()
        after = time.time()

        assert before <= incident.opened_at <= after

    def test_is_open_while_triggered_or_acknowledged(self):
        assert make_incident(state=IncidentState.TRIGGERED).is_open is True
        assert make_incident(state=IncidentState.ACKNOWLEDGED).is_open is True

    def test_is_not_open_once_resolved(self):
        assert make_incident(state=IncidentState.RESOLVED).is_open is False

    def test_acknowledge_stamps_the_time_and_keeps_it_open(self):
        incident = make_incident(incident_id=7)

        acknowledged = incident.acknowledge(at=1_700_000_000.0)

        assert acknowledged.state is IncidentState.ACKNOWLEDGED
        assert acknowledged.acknowledged_at == 1_700_000_000.0
        assert acknowledged.is_open is True
        assert acknowledged.incident_id == 7

    def test_resolve_stamps_the_time_and_closes_it(self):
        incident = make_incident()

        resolved = incident.resolve(at=1_700_000_500.0)

        assert resolved.state is IncidentState.RESOLVED
        assert resolved.resolved_at == 1_700_000_500.0
        assert resolved.is_open is False

    def test_transitions_leave_the_original_alone(self):
        """Imutável: transição devolve outro incidente, não altera este."""
        incident = make_incident()

        incident.acknowledge(at=1.0)
        incident.resolve(at=2.0)

        assert incident.state is IncidentState.TRIGGERED
        assert incident.acknowledged_at is None
        assert incident.resolved_at is None

    def test_a_new_incident_has_no_id(self):
        """Quem atribui o id é o store, ao abrir."""
        assert make_incident().incident_id is None
