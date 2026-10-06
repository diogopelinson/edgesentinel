import dataclasses
import sqlite3
import logging
import time
from pathlib import Path

import pytest

from unittest.mock import MagicMock
import application.engine
from core.rules import Rule, Condition, Severity
from core.entities import SensorReading, ActionContext, Event
from core.incidents import Incident, IncidentState
from core.ports import (
    ActionPort,
    EventPort,
    IncidentMetricsPort,
    IncidentPort,
    StatePort,
)
from application.engine import RuleEngine


# --- helpers ---

def make_action() -> MagicMock:
    """Creates an ActionPort mock to verify calls."""
    action = MagicMock(spec=ActionPort)
    return action


def make_engine(rules: list[Rule], actions: dict) -> RuleEngine:
    return RuleEngine(rules=rules, actions=actions)


# --- local fixtures ---

@pytest.fixture
def rule_above_75() -> Rule:
    return Rule(
        name="alta_temp",
        condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
        action_ids=["log", "webhook"],
    )


@pytest.fixture
def reading_72() -> SensorReading:
    return SensorReading(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        value=72.0,
        unit="°C",
    )


@pytest.fixture
def reading_82() -> SensorReading:
    return SensorReading(
        sensor_id="cpu_temp",
        name="CPU Temperature",
        value=82.0,
        unit="°C",
    )


# --- tests ---

class TestRuleEngineDispatch:

    def test_executes_action_when_condition_matches(self, rule_above_75, reading_82):
        log_action = make_action()
        engine = make_engine(
            rules=[rule_above_75],
            actions={"log": log_action, "webhook": make_action()},
        )

        engine.evaluate(reading_82)

        log_action.execute.assert_called_once()

    def test_executes_all_action_ids_in_rule(self, rule_above_75, reading_82):
        log_action = make_action()
        webhook_action = make_action()
        engine = make_engine(
            rules=[rule_above_75],
            actions={"log": log_action, "webhook": webhook_action},
        )

        engine.evaluate(reading_82)

        log_action.execute.assert_called_once()
        webhook_action.execute.assert_called_once()

    def test_does_not_execute_when_condition_is_false(self, rule_above_75, reading_72):
        log_action = make_action()
        engine = make_engine(
            rules=[rule_above_75],
            actions={"log": log_action},
        )

        engine.evaluate(reading_72)

        log_action.execute.assert_not_called()

    def test_passes_correct_context_to_action(self, rule_above_75, reading_82):
        """Checks that the ActionContext passed to the action is correct."""
        log_action = make_action()
        engine = make_engine(
            rules=[rule_above_75],
            actions={"log": log_action},
        )

        engine.evaluate(reading_82)

        context: ActionContext = log_action.execute.call_args[0][0]
        assert context.rule_name == "alta_temp"
        assert context.reading is reading_82
        assert context.score is None

    def test_passes_score_in_context_when_provided(self, rule_above_75, reading_82, anomaly_score):
        log_action = make_action()
        engine = make_engine(
            rules=[rule_above_75],
            actions={"log": log_action},
        )

        engine.evaluate(reading_82, score=anomaly_score)

        context: ActionContext = log_action.execute.call_args[0][0]
        assert context.score is anomaly_score

    def test_skips_unknown_action_id_without_crashing(self, reading_82):
        """An action_id referenced in the rule but absent from the dict must not crash."""
        rule = Rule(
            name="teste",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["inexistente"],
        )
        engine = make_engine(rules=[rule], actions={})

        # must not raise an exception
        engine.evaluate(reading_82)

    def test_disabled_rule_is_skipped(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="desabilitada",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            enabled=False,
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)

        log_action.execute.assert_not_called()

    def test_multiple_rules_evaluated_independently(self, reading_82):
        """Two rules — only the one that matches should fire."""
        log_action = make_action()
        webhook_action = make_action()

        rule_high = Rule(
            name="alta_temp",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
        )
        rule_very_high = Rule(
            name="critica",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=90.0),
            action_ids=["webhook"],
        )

        engine = make_engine(
            rules=[rule_high, rule_very_high],
            actions={"log": log_action, "webhook": webhook_action},
        )

        engine.evaluate(reading_82)

        log_action.execute.assert_called_once()       # 82 > 75 — fires
        webhook_action.execute.assert_not_called()    # 82 < 90 — does not fire


class TestRuleEngineCooldown:

    def test_action_not_called_twice_within_cooldown(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="com_cooldown",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=60.0,
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)   # first firing — passes
        engine.evaluate(reading_82)   # second firing — blocked by the cooldown

        log_action.execute.assert_called_once()

    def test_action_called_again_after_cooldown(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="cooldown_curto",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=0.1,
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)       # first firing
        time.sleep(0.15)                  # waits for the cooldown to expire
        engine.evaluate(reading_82)       # second firing — must pass

        assert log_action.execute.call_count == 2

    def test_no_cooldown_fires_every_time(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="sem_cooldown",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=0.0,
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)
        engine.evaluate(reading_82)
        engine.evaluate(reading_82)

        assert log_action.execute.call_count == 3


class TestRuleEngineSeverityPropagation:
    """
    The severity travels in ActionContext.extras, which already exists in
    core/entities.py:25 — no ActionPort signature changes because of it.
    """

    def _context_of(self, action) -> ActionContext:
        action.execute.assert_called_once()
        return action.execute.call_args.args[0]

    def test_severity_reaches_the_action_context(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="cpu_critica",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            severity=Severity.CRITICAL,
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)

        assert self._context_of(log_action).extras["severity"] == Severity.CRITICAL

    def test_default_severity_reaches_the_action_context(self, reading_82):
        log_action = make_action()
        rule = Rule(
            name="alta_temp",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
        )
        engine = make_engine(rules=[rule], actions={"log": log_action})

        engine.evaluate(reading_82)

        assert self._context_of(log_action).extras["severity"] == Severity.WARNING

    def test_every_action_of_a_rule_receives_the_severity(self, reading_82):
        """One rule dispatches to N actions — all of them need to see the same level."""
        log_action     = make_action()
        webhook_action = make_action()
        rule = Rule(
            name="cpu_critica",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log", "webhook"],
            severity=Severity.CRITICAL,
        )
        engine = make_engine(
            rules=[rule],
            actions={"log": log_action, "webhook": webhook_action},
        )

        engine.evaluate(reading_82)

        assert self._context_of(log_action).extras["severity"] == Severity.CRITICAL
        assert self._context_of(webhook_action).extras["severity"] == Severity.CRITICAL


class TestRuleEngineEventRecording:
    """
    Every rule firing becomes an Event in the store. A firing suppressed by
    cooldown is not a firing, and a store failure must not cost the action.
    """

    @pytest.fixture
    def store(self) -> MagicMock:
        return MagicMock(spec=EventPort)

    @pytest.fixture
    def critical_rule(self) -> Rule:
        return Rule(
            name="cpu_critica",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            severity=Severity.CRITICAL,
        )

    def _recorded(self, store) -> Event:
        store.append.assert_called_once()
        return store.append.call_args.args[0]

    def test_records_an_event_when_a_rule_fires(self, store, critical_rule, reading_82):
        engine = RuleEngine(rules=[critical_rule], actions={"log": make_action()}, events=store)

        engine.evaluate(reading_82)

        event = self._recorded(store)
        assert event.rule_name     == "cpu_critica"
        assert event.sensor_id     == "cpu_temp"
        assert event.value         == pytest.approx(82.0)
        assert event.unit          == reading_82.unit
        assert event.severity      == "critical"
        assert event.anomaly_score is None

    def test_event_time_is_the_reading_time(self, store, critical_rule, reading_82):
        """
        The event happened when the sensor was read, not when the engine
        finished evaluating — on a slow tick the difference is visible.
        """
        engine = RuleEngine(rules=[critical_rule], actions={}, events=store)

        engine.evaluate(reading_82)

        assert self._recorded(store).timestamp == reading_82.timestamp

    def test_event_severity_is_a_plain_string(self, store, critical_rule, reading_82):
        """
        str(Severity.CRITICAL) is 'Severity.CRITICAL' on Python 3.10 — the value
        that reaches the store needs to be the plain text, not the enum member.
        """
        engine = RuleEngine(rules=[critical_rule], actions={}, events=store)

        engine.evaluate(reading_82)

        assert type(self._recorded(store).severity) is str

    def test_records_the_anomaly_score_when_present(
        self, store, critical_rule, reading_82, anomaly_score
    ):
        engine = RuleEngine(rules=[critical_rule], actions={}, events=store)

        engine.evaluate(reading_82, score=anomaly_score)

        assert self._recorded(store).anomaly_score == pytest.approx(0.91)

    def test_records_nothing_when_no_rule_fires(self, store, critical_rule, reading_72):
        engine = RuleEngine(rules=[critical_rule], actions={}, events=store)

        engine.evaluate(reading_72)

        store.append.assert_not_called()

    def test_cooldown_suppressed_firing_is_not_recorded(self, store, reading_82):
        rule = Rule(
            name="com_cooldown",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=[],
            cooldown_seconds=60.0,
        )
        engine = RuleEngine(rules=[rule], actions={}, events=store)

        engine.evaluate(reading_82)
        engine.evaluate(reading_82)

        store.append.assert_called_once()

    def test_store_failure_does_not_cost_the_action(self, store, critical_rule, reading_82):
        """The alert is what matters; the history is secondary."""
        store.append.side_effect = RuntimeError("disco cheio")
        log_action = make_action()
        engine = RuleEngine(rules=[critical_rule], actions={"log": log_action}, events=store)

        engine.evaluate(reading_82)

        log_action.execute.assert_called_once()

    def test_store_failure_is_logged(self, store, critical_rule, reading_82, caplog):
        store.append.side_effect = RuntimeError("disco cheio")
        engine = RuleEngine(rules=[critical_rule], actions={}, events=store)

        with caplog.at_level(logging.ERROR, logger="edgesentinel.engine"):
            engine.evaluate(reading_82)

        assert "cpu_critica" in caplog.text
        assert "disco cheio" in caplog.text


class FakeIncidents(IncidentPort):
    """
    In-memory fake with the same invariant as the database: a rule has at
    most one open incident. If the engine tries to open two, the test
    breaks here instead of passing silently.
    """

    def __init__(self) -> None:
        self.by_id: dict[int, Incident] = {}
        self.opened: list[Incident] = []
        self._next_id = 1

    def open_incident(self, incident: Incident) -> Incident:
        if any(i.rule_name == incident.rule_name and i.is_open for i in self.by_id.values()):
            raise AssertionError(f"dois incidentes abertos para '{incident.rule_name}'")

        stored = dataclasses.replace(incident, incident_id=self._next_id)
        self._next_id += 1
        self.by_id[stored.incident_id] = stored
        self.opened.append(stored)
        return stored

    def acknowledge_incident(self, incident_id: int, at: float) -> None:
        self.by_id[incident_id] = self.by_id[incident_id].acknowledge(at)

    def resolve_incident(self, incident_id: int, at: float) -> None:
        self.by_id[incident_id] = self.by_id[incident_id].resolve(at)

    def open_incidents(self) -> list[Incident]:
        return [i for i in self.by_id.values() if i.is_open]


class TestRuleEngineIncidents:
    """
    Repeated firings of the same rule form one incident, which closes when
    the reading falls back past the hysteresis margin.
    """

    @pytest.fixture
    def incidents(self) -> FakeIncidents:
        return FakeIncidents()

    @pytest.fixture
    def rule(self) -> Rule:
        # resolves at 72.0 (80 minus 10%)
        return Rule(
            name="alta_temp",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=80.0),
            action_ids=["log"],
            severity=Severity.CRITICAL,
        )

    def engine_for(self, rule, incidents, actions=None, events=None) -> RuleEngine:
        return RuleEngine(
            rules=[rule],
            actions=actions or {},
            events=events,
            incidents=incidents,
        )

    def reading(self, value: float, sensor_id: str = "cpu_temp") -> SensorReading:
        return SensorReading(sensor_id, "CPU Temperature", value, "°C")

    def test_the_first_firing_opens_an_incident(self, rule, incidents):
        engine = self.engine_for(rule, incidents)

        engine.evaluate(self.reading(85.0))

        (incident,) = incidents.open_incidents()
        assert incident.rule_name == "alta_temp"
        assert incident.sensor_id == "cpu_temp"
        assert incident.severity == "critical"
        assert incident.state is IncidentState.TRIGGERED

    def test_repeated_firings_stay_in_one_incident(self, rule, incidents):
        engine = self.engine_for(rule, incidents)

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(90.0))
        engine.evaluate(self.reading(95.0))

        assert len(incidents.opened) == 1

    def test_events_point_at_the_incident(self, rule, incidents):
        store = MagicMock(spec=EventPort)
        engine = self.engine_for(rule, incidents, events=store)

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(90.0))

        (incident,) = incidents.open_incidents()
        recorded = [chamada.args[0].incident_id for chamada in store.append.call_args_list]
        assert recorded == [incident.incident_id, incident.incident_id]

    def test_a_reading_past_the_margin_resolves_it(self, rule, incidents):
        engine = self.engine_for(rule, incidents)
        engine.evaluate(self.reading(85.0))

        engine.evaluate(self.reading(70.0))

        assert incidents.open_incidents() == []

    def test_a_reading_inside_the_margin_keeps_it_open(self, rule, incidents):
        engine = self.engine_for(rule, incidents)
        engine.evaluate(self.reading(85.0))

        engine.evaluate(self.reading(79.0))

        assert len(incidents.open_incidents()) == 1

    def test_an_oscillating_series_produces_a_single_incident(self, rule, incidents):
        """The case the hysteresis exists to avoid: flapping at the edge."""
        engine = self.engine_for(rule, incidents)

        for value in (85.0, 79.0, 81.0, 78.0, 83.0, 79.5):
            engine.evaluate(self.reading(value))

        assert len(incidents.opened) == 1
        assert len(incidents.open_incidents()) == 1

    def test_resolving_lets_a_later_episode_open_a_new_incident(self, rule, incidents):
        engine = self.engine_for(rule, incidents)

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(60.0))
        engine.evaluate(self.reading(85.0))

        assert len(incidents.opened) == 2

    def test_another_sensor_does_not_resolve_the_incident(self, rule, incidents):
        engine = self.engine_for(rule, incidents)
        engine.evaluate(self.reading(85.0))

        engine.evaluate(self.reading(10.0, sensor_id="memory_usage"))

        assert len(incidents.open_incidents()) == 1

    def test_an_acknowledged_incident_stops_dispatching_actions(self, rule, incidents):
        """Acknowledging is saying 'I already know' — the alert stops repeating."""
        log_action = make_action()
        engine = self.engine_for(rule, incidents, actions={"log": log_action})
        engine.evaluate(self.reading(85.0))
        (incident,) = incidents.open_incidents()
        incidents.acknowledge_incident(incident.incident_id, at=time.time())

        engine.evaluate(self.reading(90.0))

        log_action.execute.assert_called_once()   # only the firing before the ack

    def test_an_acknowledged_incident_still_records_events(self, rule, incidents):
        """The problem keeps happening; the history has to show that."""
        store = MagicMock(spec=EventPort)
        engine = self.engine_for(rule, incidents, events=store)
        engine.evaluate(self.reading(85.0))
        (incident,) = incidents.open_incidents()
        incidents.acknowledge_incident(incident.incident_id, at=time.time())

        engine.evaluate(self.reading(90.0))

        assert store.append.call_count == 2

    def test_an_acknowledged_incident_still_resolves(self, rule, incidents):
        engine = self.engine_for(rule, incidents)
        engine.evaluate(self.reading(85.0))
        (incident,) = incidents.open_incidents()
        incidents.acknowledge_incident(incident.incident_id, at=time.time())

        engine.evaluate(self.reading(60.0))

        assert incidents.open_incidents() == []

    def test_without_an_incident_port_nothing_changes(self, rule):
        """Incidents are optional: without the port, the engine behaves as before."""
        log_action = make_action()
        engine = RuleEngine(rules=[rule], actions={"log": log_action})

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(60.0))

        log_action.execute.assert_called_once()


class TestRuleEngineCooldownState:
    """
    The cooldown stops being a field of the Rule and goes through the StatePort.
    It is what allows swapping local state for Redis in a multi-device
    deployment without touching the engine.
    """

    @pytest.fixture
    def rule_with_cooldown(self) -> Rule:
        return Rule(
            name="com_cooldown",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=60.0,
        )

    def test_asks_the_state_for_the_rule_cooldown(self, rule_with_cooldown, reading_82):
        state = MagicMock(spec=StatePort)
        state.try_acquire.return_value = True
        engine = RuleEngine(rules=[rule_with_cooldown], actions={}, state=state)

        engine.evaluate(reading_82)

        state.try_acquire.assert_called_once()
        key, ttl = state.try_acquire.call_args.args
        assert "com_cooldown" in key
        assert ttl == pytest.approx(60.0)

    def test_does_not_fire_when_the_state_refuses(self, rule_with_cooldown, reading_82):
        state = MagicMock(spec=StatePort)
        state.try_acquire.return_value = False
        log_action = make_action()
        engine = RuleEngine(rules=[rule_with_cooldown], actions={"log": log_action}, state=state)

        engine.evaluate(reading_82)

        log_action.execute.assert_not_called()

    def test_each_rule_has_its_own_cooldown_key(self, reading_82):
        """Two rules that match the same reading must not consume a single cooldown."""
        first = Rule(
            name="primeira",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log"],
            cooldown_seconds=60.0,
        )
        second = Rule(
            name="segunda",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=80.0),
            action_ids=["log"],
            cooldown_seconds=60.0,
        )
        log_action = make_action()
        engine = make_engine(rules=[first, second], actions={"log": log_action})

        engine.evaluate(reading_82)

        assert log_action.execute.call_count == 2

    def test_rules_no_longer_carry_cooldown_state(self, rule_with_cooldown):
        """The state left the entity: the Rule goes back to being only the rule declaration."""
        assert not hasattr(rule_with_cooldown, "_last_triggered")

    def test_the_engine_does_not_read_the_clock_itself(self):
        """
        time.monotonic() does not cross processes — its epoch is per process.
        If the engine goes back to comparing timestamps, RedisState has no way
        to make the cooldown hold across devices.
        """
        source = Path(application.engine.__file__).read_text(encoding="utf-8")

        assert "monotonic" not in source

class BrokenIncidents(FakeIncidents):
    """
    Incident store that fails on one operation and works on all the rest —
    locked database, full disk, Redis down. `failing` can be cleared
    mid-test to simulate the service coming back.
    """

    def __init__(self, failing: str) -> None:
        super().__init__()
        self.failing: str | None = failing
        self.attempts = 0

    def _maybe_fail(self, operation: str) -> None:
        if operation == self.failing:
            self.attempts += 1
            raise sqlite3.OperationalError("database is locked")

    def open_incident(self, incident: Incident) -> Incident:
        self._maybe_fail("open_incident")
        return super().open_incident(incident)

    def resolve_incident(self, incident_id: int, at: float) -> None:
        self._maybe_fail("resolve_incident")
        super().resolve_incident(incident_id, at)

    def open_incidents(self) -> list[Incident]:
        self._maybe_fail("open_incidents")
        return super().open_incidents()


class TestRuleEngineSurvivesAnIncidentStoreFailure:
    """
    The incident is context for the alarm, not the alarm. If the incident store
    goes down, the firing still goes out and the history is still written:
    the opposite would let a full disk silence a critical temperature.
    """

    @pytest.fixture
    def rule(self) -> Rule:
        # resolves at 72.0 (80 minus 10%)
        return Rule(
            name="alta_temp",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=80.0),
            action_ids=["log"],
            severity=Severity.CRITICAL,
        )

    def engine_for(self, rule, incidents, actions=None, events=None) -> RuleEngine:
        return RuleEngine(
            rules=[rule],
            actions=actions or {},
            events=events,
            incidents=incidents,
        )

    def reading(self, value: float) -> SensorReading:
        return SensorReading("cpu_temp", "CPU Temperature", value, "°C")

    def test_a_failing_open_still_alerts_and_records(self, rule, caplog):
        """Without an incident, the event goes to the history without an incident_id."""
        incidents = BrokenIncidents("open_incident")
        log_action = make_action()
        store = MagicMock(spec=EventPort)
        engine = self.engine_for(rule, incidents, actions={"log": log_action}, events=store)

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(85.0))

        log_action.execute.assert_called_once()
        assert store.append.call_args.args[0].incident_id is None
        assert "alta_temp" in caplog.text

    def test_a_failing_read_of_the_open_incidents_still_alerts(self, rule, caplog):
        incidents = BrokenIncidents("open_incidents")
        log_action = make_action()
        engine = self.engine_for(rule, incidents, actions={"log": log_action})

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(85.0))

        log_action.execute.assert_called_once()
        assert caplog.records, "a falha foi engolida sem registro"

    def test_a_blind_engine_cannot_duplicate_the_incident(self, rule, caplog):
        """
        Unable to read the open ones, the engine tries to open another on every
        firing. What refuses is the unique index of the database — here, the same
        invariant in the fake — and the refusal must not stop the alert.
        """
        incidents = BrokenIncidents("open_incidents")
        log_action = make_action()
        engine = self.engine_for(rule, incidents, actions={"log": log_action})

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(85.0))
            engine.evaluate(self.reading(90.0))

        assert len(incidents.opened) == 1
        assert log_action.execute.call_count == 2

    def test_a_failing_resolve_keeps_the_incident_open_for_the_next_reading(self, rule, caplog):
        """
        Failing to close must not leave the incident half closed: it
        stays open and the next reading tries again, because the engine
        re-reads the state on every evaluation instead of keeping it in memory.
        """
        incidents = BrokenIncidents("resolve_incident")
        engine = self.engine_for(rule, incidents)
        engine.evaluate(self.reading(85.0))

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(70.0))

        assert len(incidents.open_incidents()) == 1
        assert incidents.attempts == 1
        assert "alta_temp" in caplog.text

        incidents.failing = None
        engine.evaluate(self.reading(69.0))

        assert incidents.open_incidents() == []


class FakeMetrics(IncidentMetricsPort):
    """Records what was counted, so the test can compare it with the cycle."""

    def __init__(self, failing: bool = False) -> None:
        self.opened: list[Incident] = []
        self.resolved: list[tuple[Incident, float]] = []
        self.failing = failing

    def record_incident_opened(self, incident: Incident) -> None:
        if self.failing:
            raise RuntimeError("exporter fora do ar")
        self.opened.append(incident)

    def record_incident_resolved(self, incident: Incident, duration_seconds: float) -> None:
        if self.failing:
            raise RuntimeError("exporter fora do ar")
        self.resolved.append((incident, duration_seconds))


class TestRuleEngineIncidentMetrics:
    """
    The engine is the one that sees the transitions, so the counting comes from
    it. The gauge of open ones does not go through here: whoever publishes reads
    the store at scrape time, because the engine keeps no incident in memory.
    """

    @pytest.fixture
    def incidents(self) -> FakeIncidents:
        return FakeIncidents()

    @pytest.fixture
    def metrics(self) -> FakeMetrics:
        return FakeMetrics()

    @pytest.fixture
    def rule(self) -> Rule:
        # resolves at 72.0 (80 minus 10%)
        return Rule(
            name="alta_temp",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=80.0),
            action_ids=["log"],
            severity=Severity.CRITICAL,
        )

    def engine_for(self, rule, incidents, metrics) -> RuleEngine:
        return RuleEngine(
            rules=[rule], actions={}, incidents=incidents, metrics=metrics,
        )

    def reading(self, value: float, timestamp: float | None = None) -> SensorReading:
        reading = SensorReading("cpu_temp", "CPU Temperature", value, "°C")
        if timestamp is None:
            return reading
        return dataclasses.replace(reading, timestamp=timestamp)

    def test_opening_an_incident_is_counted(self, rule, incidents, metrics):
        engine = self.engine_for(rule, incidents, metrics)

        engine.evaluate(self.reading(85.0))

        (contado,) = metrics.opened
        assert contado.rule_name == "alta_temp"
        assert contado.severity == "critical"

    def test_a_firing_that_joins_an_incident_is_not_counted_again(
        self, rule, incidents, metrics,
    ):
        """
        The counter counts episodes, not firings — the firing already has its own
        in edgesentinel_rule_triggered_total. Counting it again here would make
        the opening rate follow the reading frequency.
        """
        engine = self.engine_for(rule, incidents, metrics)

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(90.0))

        assert len(metrics.opened) == 1

    def test_resolving_is_counted_with_the_duration(self, rule, incidents, metrics):
        engine = self.engine_for(rule, incidents, metrics)

        engine.evaluate(self.reading(85.0, timestamp=1_000.0))
        engine.evaluate(self.reading(70.0, timestamp=1_045.0))

        (contado, duracao) = metrics.resolved[0]
        assert contado.rule_name == "alta_temp"
        assert duracao == 45.0

    def test_the_duration_is_measured_from_the_readings_not_the_clock(
        self, rule, incidents, metrics,
    ):
        """
        The duration of the incident is the distance between the two readings
        that opened and closed it. Measuring with the clock of the evaluation
        would give the time the engine took to run, not how long the problem
        lasted.
        """
        engine = self.engine_for(rule, incidents, metrics)

        engine.evaluate(self.reading(85.0, timestamp=5_000.0))
        engine.evaluate(self.reading(60.0, timestamp=5_120.0))

        assert metrics.resolved[0][1] == 120.0

    def test_a_failed_resolve_is_not_counted(self, rule, metrics):
        """
        Counting a close that the database refused would make the sum of
        opened minus closed diverge from what is on disk.
        """
        incidents = BrokenIncidents("resolve_incident")
        engine = self.engine_for(rule, incidents, metrics)

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(70.0))

        assert metrics.resolved == []

    def test_a_failed_open_is_not_counted(self, rule, metrics):
        incidents = BrokenIncidents("open_incident")
        engine = self.engine_for(rule, incidents, metrics)

        engine.evaluate(self.reading(85.0))

        assert metrics.opened == []

    def test_a_broken_exporter_does_not_cost_the_alert(self, rule, incidents):
        """
        A metric is an observation of the alarm, not the alarm. An exporter that
        raises must not prevent the action from running nor the incident from
        opening.
        """
        log_action = make_action()
        engine = RuleEngine(
            rules=[rule],
            actions={"log": log_action},
            incidents=incidents,
            metrics=FakeMetrics(failing=True),
        )

        engine.evaluate(self.reading(85.0))

        log_action.execute.assert_called_once()
        assert len(incidents.open_incidents()) == 1

    def test_a_broken_exporter_is_logged(self, rule, incidents, caplog):
        engine = RuleEngine(
            rules=[rule], actions={}, incidents=incidents,
            metrics=FakeMetrics(failing=True),
        )

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(85.0))

        assert "exporter fora do ar" in caplog.text

    def test_a_broken_exporter_does_not_look_like_a_failed_open(
        self, rule, incidents, caplog,
    ):
        """
        Found by mutation: counting the opening used to sit inside the try that
        protects the store, and a metric that raised fell into that except. The
        database had already opened the incident, but the engine returned None —
        the event of that firing went out without an incident_id and the log said
        the opening had failed. Counting comes after opening, not inside it.
        """
        store = MagicMock(spec=EventPort)
        engine = RuleEngine(
            rules=[rule], actions={}, events=store,
            incidents=incidents, metrics=FakeMetrics(failing=True),
        )

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(85.0))

        (incident,) = incidents.open_incidents()
        assert store.append.call_args.args[0].incident_id == incident.incident_id
        assert "Falha ao abrir incidente" not in caplog.text

    def test_a_broken_exporter_does_not_look_like_a_failed_resolve(
        self, rule, incidents, caplog,
    ):
        """
        The same on closing: the incident closes in the database and the log
        must not say that the close failed, or the operator will go looking for
        an incident that is already resolved.
        """
        engine = RuleEngine(
            rules=[rule], actions={},
            incidents=incidents, metrics=FakeMetrics(failing=True),
        )
        engine.evaluate(self.reading(85.0))

        with caplog.at_level(logging.ERROR):
            engine.evaluate(self.reading(70.0))

        assert incidents.open_incidents() == []
        assert "Falha ao resolver incidente" not in caplog.text

    def test_without_a_metrics_port_the_engine_works_the_same(self, rule, incidents):
        engine = RuleEngine(rules=[rule], actions={}, incidents=incidents)

        engine.evaluate(self.reading(85.0))
        engine.evaluate(self.reading(70.0))

        assert incidents.open_incidents() == []
