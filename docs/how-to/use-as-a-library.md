# Use edgesentinel as a library

Embedding the agent in your own Python process instead of running the CLI.

## Simplest case — load from config.yaml

```python
from config.loader import load
from cli.builder import build_monitor

config  = load("config.yaml")
monitor = build_monitor(config)
monitor.start()   # blocking — Ctrl+C shuts down cleanly
```

## Full control — assembling manually

```python
from adapters.sensors.cpu_temp import CpuTemperatureSensor
from adapters.sensors.simulated import SimulatedSensor
from adapters.inference.remote import RemoteInferenceAdapter
from adapters.actions.log import LogAction
from adapters.actions.webhook import WebhookAction
from adapters.exporter.prometheus import PrometheusExporter
from adapters.store.sqlite import SQLiteEventStore
from application.engine import RuleEngine
from application.pipeline import Pipeline
from application.monitor import MonitorLoop
from core.rules import Rule, Condition, Severity

sensors = [
    CpuTemperatureSensor(sensor_id="cpu_temp"),
    SimulatedSensor("cpu_usage", "CPU", "%", base_value=60.0, scenario="stress"),
]

inference = RemoteInferenceAdapter(
    model_id="yolo_v8n",
    service_url="http://localhost:8080",
    threshold=0.5,
)
inference.load("")

actions = {
    "log":     LogAction(action_id="log"),
    "webhook": WebhookAction(action_id="webhook",
                             url="https://hooks.example.com/alert"),
}

rules = [
    Rule(
        name="high_temperature",
        condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
        action_ids=["log", "webhook"],
        cooldown_seconds=60.0,
        # no severity: Severity.WARNING
    ),
    Rule(
        name="critical_temperature",
        condition=Condition(sensor_id="cpu_temp", operator=">", threshold=85.0),
        action_ids=["log", "webhook"],
        severity=Severity.CRITICAL,
        cooldown_seconds=30.0,
    ),
]

exporter  = PrometheusExporter(port=8000)
events    = SQLiteEventStore(path="data/events.db", retention_days=30)
engine    = RuleEngine(rules=rules, actions=actions, events=events)
pipelines = [
    Pipeline(sensor=s, engine=engine, inference=inference, exporter=exporter)
    for s in sensors
]

monitor = MonitorLoop(
    pipelines=pipelines,
    poll_interval_seconds=5.0,
    exporter=exporter,
    event_store=events,   # the loop opens the store on start and flushes the queue on shutdown
)
monitor.start()
```

`events` is optional in both places: without it nothing is recorded and everything else works the same. The same object must go to `RuleEngine`, which writes, and to `MonitorLoop`, which owns the lifecycle.

`default_actions` is a `config.yaml` feature, resolved by `config.mapper.to_rules` before rules reach the engine. Rules assembled by hand, as above, carry `action_ids` already resolved — `RuleEngine` only ever sees the final list. To use severity routing without YAML, build an `EdgeSentinelConfig` and pass it through `to_rules`:

```python
from config.mapper import to_rules
from config.schema import ConditionConfig, EdgeSentinelConfig, RuleConfig

config = EdgeSentinelConfig(
    sensors=[], actions=[],
    default_actions={"warning": ["log"], "critical": ["log", "webhook"]},
    rules=[
        RuleConfig(
            name="critical_temperature",
            condition=ConditionConfig(sensor_id="cpu_temp", operator=">", threshold=85.0),
            severity="critical",
        ),
    ],
)
rules = to_rules(config)   # rules[0].action_ids == ["log", "webhook"]
```

## Querying the history

```python
import time
from adapters.store.sqlite import SQLiteEventStore

store = SQLiteEventStore(path="data/events.db")
store.start()
try:
    critical_24h = store.query(
        severity="critical",
        since=time.time() - 24 * 3600,
        limit=20,
    )
    for e in critical_24h:
        print(e.event_id, e.rule_name, e.sensor_id, e.value, e.unit, e.anomaly_score)
finally:
    store.close()
```

- Combinable filters: `severity`, `sensor_id`, `rule_name`, `since` and `until` (both inclusive, Unix timestamps) and `limit` (default 100).
- Results come newest first.
- `start()` applies retention: events older than `retention_days` are removed on open.
- `start()` creates the file and its folders if they do not exist.

---
