"""
Incident resolution with hysteresis.

An incident does not close at the same point where it opened. Without a margin,
a value oscillating at the edge of the threshold opens and closes an incident on
every reading — flapping. The condition only resolves when the reading falls
back past the margin.
"""
import pytest

from core.entities import AnomalyScore, SensorReading
from core.rules import Condition


def reading(value: float, sensor_id: str = "cpu_temp") -> SensorReading:
    return SensorReading(sensor_id, "CPU Temperature", value, "°C")


def score(is_anomaly: bool) -> AnomalyScore:
    return AnomalyScore(
        score=0.9 if is_anomaly else 0.1,
        threshold=0.7,
        is_anomaly=is_anomaly,
        model_id="dummy",
        reading=reading(80.0),
    )


class TestResolutionPoint:
    """The default margin is 10% of |threshold|, towards the side opposite the alarm."""

    @pytest.mark.parametrize("operator, threshold, expected", [
        (">",  80.0, 72.0),
        (">=", 80.0, 72.0),
        ("<",  20.0, 22.0),
        ("<=", 20.0, 22.0),
    ])
    def test_margin_moves_away_from_the_alarm(self, operator, threshold, expected):
        point = Condition("cpu_temp", operator, threshold).resolution_point()

        assert point == pytest.approx(expected)

    @pytest.mark.parametrize("operator, expected", [(">", -11.0), ("<", -9.0)])
    def test_a_negative_threshold_also_moves_away_from_the_alarm(self, operator, expected):
        """
        With threshold -10 and operator '>', multiplying by 0.9 would give -9,
        which is on the alarm side: the incident would close by itself.
        """
        point = Condition("cpu_temp", operator, -10.0).resolution_point()

        assert point == pytest.approx(expected)

    def test_a_zero_threshold_has_no_margin(self):
        assert Condition("cpu_temp", ">", 0.0).resolution_point() == pytest.approx(0.0)

    def test_an_explicit_resolve_threshold_wins(self):
        condition = Condition("cpu_temp", ">", 80.0, resolve_threshold=70.0)

        assert condition.resolution_point() == pytest.approx(70.0)

    @pytest.mark.parametrize("operator", ["==", "anomaly"])
    def test_operators_without_a_numeric_edge_have_no_point(self, operator):
        assert Condition("cpu_temp", operator, 0.0).resolution_point() is None


class TestResolves:

    def test_an_upper_bound_resolves_past_the_margin(self):
        condition = Condition("cpu_temp", ">", 80.0)

        assert condition.resolves(reading(72.0)) is True
        assert condition.resolves(reading(60.0)) is True

    def test_a_value_inside_the_margin_keeps_the_incident_open(self):
        """
        79 °C does not fire the rule, but it does not resolve either: it is the
        band that avoids flapping.
        """
        condition = Condition("cpu_temp", ">", 80.0)

        assert condition.evaluate(reading(79.0)) is False
        assert condition.resolves(reading(79.0)) is False

    def test_a_value_still_in_alarm_does_not_resolve(self):
        assert Condition("cpu_temp", ">", 80.0).resolves(reading(85.0)) is False

    def test_a_lower_bound_resolves_past_the_margin(self):
        condition = Condition("cpu_temp", "<", 20.0)

        assert condition.resolves(reading(22.0)) is True
        assert condition.resolves(reading(21.0)) is False

    def test_a_reading_from_another_sensor_never_resolves(self):
        condition = Condition("cpu_temp", ">", 80.0)

        assert condition.resolves(reading(10.0, sensor_id="memory_usage")) is False

    def test_equality_resolves_as_soon_as_the_value_changes(self):
        """'==' has no margin: leaving the exact value is already leaving the alarm."""
        condition = Condition("cpu_temp", "==", 0.0)

        assert condition.resolves(reading(0.0)) is False
        assert condition.resolves(reading(1.0)) is True

    def test_anomaly_resolves_when_the_score_drops(self):
        condition = Condition("cpu_temp", "anomaly")

        assert condition.resolves(reading(80.0), score(is_anomaly=False)) is True
        assert condition.resolves(reading(80.0), score(is_anomaly=True)) is False

    def test_anomaly_does_not_resolve_without_a_score(self):
        """
        Inference being down is not good news: with no score there is no
        information to close the incident with.
        """
        assert Condition("cpu_temp", "anomaly").resolves(reading(80.0), None) is False

    def test_an_unknown_operator_never_resolves(self):
        """
        A domain guard. The loader refuses an unknown operator, but if a new
        operator arrives without a closing rule, the incident has to stay
        open — closing it by mistake makes the alarm disappear.
        """
        condition = Condition("cpu_temp", "~=", 80.0)

        assert condition.resolution_point() is None
        assert condition.resolves(reading(10.0)) is False
