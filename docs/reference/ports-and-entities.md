# Ports and entities

Every contract in core/ports.py and every dataclass in core/entities.py, core/rules.py and core/incidents.py.

## `SensorPort`

```python
class SensorPort(ABC):
    def read(self) -> SensorReading: ...
    def is_available(self) -> bool: ...
```

## `InferencePort`

```python
class InferencePort(ABC):
    def predict(self, reading: SensorReading) -> AnomalyScore: ...
    def load(self, model_path: str) -> None: ...
```

## `ActionPort`

```python
class ActionPort(ABC):
    def execute(self, context: ActionContext) -> None: ...
```

## `EventPort`

```python
class EventPort(ABC):
    def start(self) -> None: ...                 # constructing never touches the disk
    def append(self, event: Event) -> None: ...  # never blocks the caller
    def query(self, *, severity=None, sensor_id=None, rule_name=None,
              since=None, until=None, limit=100) -> list[Event]: ...
    def prune(self, before: float) -> int: ...   # returns how many were removed
    def close(self) -> None: ...                 # writes whatever is pending
```

## `StatePort`

```python
class StatePort(ABC):
    # takes the key for ttl_seconds; False while a previous take is alive.
    # taking and checking are one atomic operation, and no timestamp is
    # exposed: a monotonic epoch means nothing in another process
    def try_acquire(self, key: str, ttl_seconds: float) -> bool: ...
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
```

`RuleEngine` uses it for rule cooldowns, under the key `cooldown:<rule name>`, and defaults to `adapters.state.memory.InMemoryState` — per-process state, backed by `time.monotonic()`. Pass your own with `RuleEngine(..., state=my_state)`; the Redis adapter that makes cooldowns hold across devices will plug in the same way. Any implementation must pass `tests/adapters/test_state_contract.py`.

## `IncidentPort`

```python
class IncidentPort(ABC):
    # returns the incident with the incident_id assigned by the store
    def open_incident(self, incident: Incident) -> Incident: ...
    def acknowledge_incident(self, incident_id: int, at: float) -> None: ...
    def resolve_incident(self, incident_id: int, at: float) -> None: ...
    def open_incidents(self) -> list[Incident]: ...   # oldest first
```

`SQLiteEventStore` implements this port alongside `EventPort`, so events and incidents land in the same file and a single `close()` flushes both. Unlike `StatePort`, this state has to be durable and queryable: an operator lists what is open and acknowledges it from another process.

Two rules any implementation has to keep, both covered by `tests/adapters/test_sqlite_incidents.py`: a rule has at most one open incident — in SQLite that is a partial unique index, `UNIQUE (rule_name) WHERE state != 'resolved'`, so a concurrent open is refused by the storage rather than by a lock in the engine — and `open_incidents()` returns acknowledged incidents too, because being acknowledged does not close anything.

Pass an implementation with `RuleEngine(..., incidents=my_store)`. With none, the engine still evaluates, alerts and records: events are written with `incident_id` empty. It treats a raising store the same way, since an incident is context around an alarm and must not be able to silence it.

## `SensorReading`

```python
@dataclass(frozen=True)
class SensorReading:
    sensor_id: str
    name: str
    value: float
    unit: str
    timestamp: float        # auto-generated via time.time()
    metadata: dict          # camera frames live here
```

## `AnomalyScore`

```python
@dataclass(frozen=True)
class AnomalyScore:
    score: float            # 0.0 = normal, 1.0 = full anomaly
    threshold: float
    is_anomaly: bool        # score >= threshold
    model_id: str
    reading: SensorReading
```

## `ActionContext`

```python
@dataclass
class ActionContext:
    rule_name: str
    reading: SensorReading
    score: AnomalyScore | None
    extras: dict            # extras["severity"] carries the rule's Severity
```

## `Event`

```python
@dataclass(frozen=True)
class Event:
    rule_name: str
    sensor_id: str
    value: float
    unit: str
    severity: str                   # plain text: "info", "warning", "critical"
    timestamp: float                # time of the reading, not of evaluation
    anomaly_score: float | None     # None for rules without inference
    event_id: int | None            # assigned by the store on write
    incident_id: int | None         # the episode this firing belongs to
```

## `Incident`

```python
@dataclass(frozen=True)
class Incident:
    rule_name: str
    sensor_id: str
    severity: str                       # plain text, like Event.severity
    state: IncidentState = IncidentState.TRIGGERED
    opened_at: float = field(default_factory=time.time)
    acknowledged_at: float | None = None
    resolved_at: float | None = None
    incident_id: int | None = None      # assigned by the store on open

    @property
    def is_open(self) -> bool: ...              # acknowledged still counts as open
    def acknowledge(self, at: float) -> "Incident": ...
    def resolve(self, at: float) -> "Incident": ...
```

Frozen like the other entities: the transitions return a new incident instead of mutating one.

## `IncidentState`

```python
class IncidentState(str, Enum):
    TRIGGERED    = "triggered"      # open, alerting on every firing
    ACKNOWLEDGED = "acknowledged"   # the history keeps recording, the actions stop
    RESOLVED     = "resolved"       # closed; the next firing opens a new incident
```

There is no `normal` state. Normal is the absence of an open incident — storing it would mean a row for every rule that has never fired.

## `Rule`

```python
@dataclass
class Rule:
    name: str
    condition: Condition
    action_ids: list[str]
    severity: Severity = Severity.WARNING
    enabled: bool = True
    cooldown_seconds: float = 0.0
```

## `Severity`

```python
class Severity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"     # default
    CRITICAL = "critical"

    @classmethod
    def from_name(cls, name: str) -> "Severity": ...   # case-insensitive
```

| Severity | `log` level | Typical use |
|---|---|---|
| `info` | INFO | expected event worth recording |
| `warning` | WARNING | out of the ordinary, needs attention — **default** |
| `critical` | CRITICAL | requires immediate action |

## Action resolution (`default_actions`)

| The rule declares | `default_actions` has the rule's severity | Actions dispatched |
|---|---|---|
| `actions: [log]` | either way | `[log]` — the rule's list, not added to the default |
| `actions: []` | either way | none — the event still goes to the history |
| nothing | yes | the `default_actions` list for that severity |
| nothing | no | none |

Rules with no actions at all are logged at `DEBUG` on the `edgesentinel.config` logger. In `config.yaml`, an unknown severity in `default_actions`, the same severity written twice (`warning` and `Warning`), a list that is not made of ids, and a rule's `actions` written as a mapping all fail at load time.

## Available operators

| Operator | Description | Example |
|---|---|---|
| `>` | greater than | `cpu_temp > 75` |
| `<` | less than | `cpu_temp < 10` |
| `>=` | greater or equal | `cpu_usage >= 90` |
| `<=` | less or equal | `memory_usage <= 20` |
| `==` | equal | `cpu_temp == 0` (dead sensor) |

A condition with an upper or lower bound also takes `resolve_threshold`, the value where the incident closes:

```yaml
condition:
  sensor_id: cpu_temp
  operator: ">"
  threshold: 85.0
  resolve_threshold: 80.0     # default would be 76.5
```

Without it the closing point is the threshold minus 10% of its absolute value, moved away from the alarm: `> 80` closes at 72, `< 10` closes at 11, and a threshold of 0 has no margin. The loader refuses a value on the alarm side of the threshold — `> 85` resolving at 90 would close the incident with the sensor still over the limit — and refuses the field on the two operators with no numeric edge: `==` closes as soon as the value changes, and `anomaly` closes when the score comes back under its own threshold. With inference down there is no score, and no score means no resolution: the incident stays open.

| `anomaly` | ML score above threshold | camera, any sensor |
