import dataclasses
import time

import pytest

from core.entities import Event


def make_event(**overrides) -> Event:
    fields = dict(
        rule_name="alta_temperatura",
        sensor_id="cpu_temp",
        value=82.4,
        unit="°C",
        severity="critical",
    )
    fields.update(overrides)
    return Event(**fields)


class TestEvent:

    def test_is_immutable(self):
        """Como as demais entidades do core — o loop é concorrente."""
        event = make_event()

        with pytest.raises(dataclasses.FrozenInstanceError):
            event.value = 99.0

    def test_timestamp_defaults_to_now(self):
        before = time.time()
        event  = make_event()
        after  = time.time()

        assert before <= event.timestamp <= after

    def test_anomaly_score_is_optional(self):
        """Regra de threshold dispara sem inferência nenhuma."""
        assert make_event().anomaly_score is None

    def test_carries_anomaly_score_when_present(self):
        assert make_event(anomaly_score=0.93).anomaly_score == pytest.approx(0.93)

    def test_event_id_is_assigned_by_the_store(self):
        """Quem ainda não foi persistido não tem id."""
        assert make_event().event_id is None
