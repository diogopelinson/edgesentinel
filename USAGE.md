# Using edgesentinel as a library

`edgesentinel` can be used in two ways: via CLI (`edgesentinel run`) or imported directly into your Python code as a library. This guide covers the second approach.

---

## Installation

```bash
pip install edgesentinel[onnx]
```

---

## Case 1 — Simplest usage: load from config.yaml

If you already have a `config.yaml`, you can assemble and start the system in a few lines:

```python
from config.loader import load
from cli.builder import build_monitor

# load config.yaml and assemble the full system
config  = load("config.yaml")
monitor = build_monitor(config)

# start the monitoring loop (blocking)
monitor.start()
```

This is equivalent to running `edgesentinel run --config config.yaml`.

---

## Case 2 — Full control: assembling the pieces manually

If you want more control — custom sensors, dynamic rule logic, integration with your own system — you can assemble each piece separately.

### Step 1: create sensors

```python
from adapters.sensors.cpu_temp import CpuTemperatureSensor
from adapters.sensors.memory_usage import MemoryUsageSensor
from adapters.sensors.simulated import SimulatedSensor

# real sensors (require Linux)
cpu_sensor = CpuTemperatureSensor(sensor_id="cpu_temp")
mem_sensor = MemoryUsageSensor(sensor_id="memory_usage")

# simulated sensor (works on any OS — useful for testing)
sim_sensor = SimulatedSensor(
    sensor_id="cpu_temp",
    name="CPU Temperature",
    unit="°C",
    base_value=58.0,
    amplitude=5.0,
    scenario="stress",   # normal | stress | spike
)
```

### Step 2: create the inference backend

```python
from adapters.inference.dummy import DummyInferenceAdapter
from adapters.inference.onnx import ONNXInferenceAdapter

# dummy — always returns score 0.0, useful for development
inference = DummyInferenceAdapter()

# ONNX — real model trained with scripts/train_model.py
inference = ONNXInferenceAdapter(threshold=0.7)
inference.load("models/anomaly.onnx")
```

### Step 3: create actions

```python
from adapters.actions.log import LogAction
from adapters.actions.webhook import WebhookAction

log_action     = LogAction(action_id="log", level="WARNING")
webhook_action = WebhookAction(
    action_id="webhook",
    url="https://hooks.example.com/alert",
    timeout_seconds=5.0,
)

actions = {
    "log":     log_action,
    "webhook": webhook_action,
}
```

### Step 4: create rules

```python
from core.rules import Rule, Condition

rules = [
    Rule(
        name="high_temperature",
        condition=Condition(
            sensor_id="cpu_temp",
            operator=">",       # > < >= <= == anomaly
            threshold=75.0,
        ),
        action_ids=["log", "webhook"],
        cooldown_seconds=60.0,
    ),
    Rule(
        name="ml_anomaly",
        condition=Condition(
            sensor_id="cpu_temp",
            operator="anomaly",   # uses the ML model score
        ),
        action_ids=["log"],
        cooldown_seconds=30.0,
    ),
]
```

### Step 5: assemble the engine and pipeline

```python
from application.engine import RuleEngine
from application.pipeline import Pipeline
from adapters.exporter.prometheus import PrometheusExporter

# exporter is optional — exposes /metrics on port 8000
exporter = PrometheusExporter(port=8000)
exporter.start()

engine = RuleEngine(rules=rules, actions=actions)

pipeline = Pipeline(
    sensor=cpu_sensor,
    engine=engine,
    inference=inference,
    exporter=exporter,    # optional
)
```

### Step 6: run

```python
import time

while True:
    pipeline.run_once()
    time.sleep(5)
```

Or use `MonitorLoop` for an async loop with graceful shutdown:

```python
from application.monitor import MonitorLoop

monitor = MonitorLoop(
    pipelines=[pipeline],
    poll_interval_seconds=5.0,
    exporter=exporter,
)

monitor.start()   # blocking — Ctrl+C shuts down cleanly
```

---

## Case 3 — Creating your own sensor

Implement `SensorPort` from `core/ports.py`:

```python
from core.ports import SensorPort
from core.entities import SensorReading


class MyCustomSensor(SensorPort):
    """
    Sensor that reads from any source — file, serial, I2C, API, etc.
    """

    def __init__(self, sensor_id: str) -> None:
        self.sensor_id = sensor_id

    def read(self) -> SensorReading:
        value = self._read_hardware()
        return SensorReading(
            sensor_id=self.sensor_id,
            name="My Sensor",
            value=value,
            unit="°C",
        )

    def is_available(self) -> bool:
        try:
            self.read()
            return True
        except Exception:
            return False

    def _read_hardware(self) -> float:
        # read from a file, serial port, I2C, API, etc.
        return 42.0
```

Plug it into the system:

```python
my_sensor = MyCustomSensor(sensor_id="my_sensor")

pipeline = Pipeline(
    sensor=my_sensor,
    engine=engine,
    inference=inference,
)
```

---

## Case 4 — Creating your own action

Implement `ActionPort` from `core/ports.py`:

```python
from core.ports import ActionPort
from core.entities import ActionContext
import requests


class SlackAction(ActionPort):
    """Sends a formatted message to a Slack channel."""

    def __init__(self, action_id: str, webhook_url: str) -> None:
        self.action_id = action_id
        self.webhook_url = webhook_url

    def execute(self, context: ActionContext) -> None:
        reading = context.reading
        score   = context.score

        text = (
            f":warning: *{context.rule_name}*\n"
            f"Sensor: `{reading.sensor_id}` — "
            f"Value: `{reading.value}{reading.unit}`"
        )

        if score is not None and score.is_anomaly:
            text += f"\nAnomaly score: `{score.score:.2f}`"

        requests.post(self.webhook_url, json={"text": text}, timeout=5)
```

---

## Case 5 — Reading a sensor directly (no pipeline)

If you just want to read a sensor and use the value in your code:

```python
from adapters.sensors.cpu_temp import CpuTemperatureSensor

sensor = CpuTemperatureSensor(sensor_id="cpu_temp")

if sensor.is_available():
    reading = sensor.read()
    print(f"{reading.name}: {reading.value}{reading.unit}")
    # CPU Temperature: 62.5°C
```

---

## Case 6 — Running inference directly (no pipeline)

If you just want to use the anomaly model in your code:

```python
from adapters.inference.onnx import ONNXInferenceAdapter
from core.entities import SensorReading

adapter = ONNXInferenceAdapter(threshold=0.7)
adapter.load("models/anomaly.onnx")

reading = SensorReading(
    sensor_id="cpu_temp",
    name="CPU Temperature",
    value=85.0,
    unit="°C",
)

score = adapter.predict(reading)

print(f"Score: {score.score:.3f}")
print(f"Is anomaly: {score.is_anomaly}")
# Score: 0.937
# Is anomaly: True
```

---

## Interface reference

### `SensorPort`

```python
class SensorPort(ABC):
    def read(self) -> SensorReading: ...       # reads one measurement
    def is_available(self) -> bool: ...        # checks if sensor exists
```

### `InferencePort`

```python
class InferencePort(ABC):
    def predict(self, reading: SensorReading) -> AnomalyScore: ...
    def load(self, model_path: str) -> None: ...
```

### `ActionPort`

```python
class ActionPort(ABC):
    def execute(self, context: ActionContext) -> None: ...
```

### `SensorReading`

```python
@dataclass(frozen=True)
class SensorReading:
    sensor_id: str
    name: str
    value: float
    unit: str
    timestamp: float      # auto-generated
    metadata: dict        # optional extra fields
```

### `AnomalyScore`

```python
@dataclass(frozen=True)
class AnomalyScore:
    score: float          # 0.0 = normal, 1.0 = full anomaly
    threshold: float      # configured threshold
    is_anomaly: bool      # score >= threshold
    model_id: str
    reading: SensorReading
```

### `ActionContext`

```python
@dataclass
class ActionContext:
    rule_name: str
    reading: SensorReading
    score: AnomalyScore | None    # None if inference is disabled
    extras: dict                   # optional extra data
```

### `Rule`

```python
@dataclass
class Rule:
    name: str
    condition: Condition
    action_ids: list[str]
    enabled: bool = True
    cooldown_seconds: float = 0.0
```

### `Condition`

```python
@dataclass
class Condition:
    sensor_id: str
    operator: str        # ">" | "<" | ">=" | "<=" | "==" | "anomaly"
    threshold: float = 0.0
```

---

## Full example

Self-contained script that runs the full system programmatically:

```python
from adapters.sensors.simulated import SimulatedSensor
from adapters.inference.onnx import ONNXInferenceAdapter
from adapters.actions.log import LogAction
from adapters.actions.webhook import WebhookAction
from adapters.exporter.prometheus import PrometheusExporter
from application.engine import RuleEngine
from application.pipeline import Pipeline
from application.monitor import MonitorLoop
from core.rules import Rule, Condition


def main():
    # sensors
    sensors = [
        SimulatedSensor("cpu_temp",  "CPU Temperature", "°C", base_value=60.0, scenario="stress"),
        SimulatedSensor("cpu_usage", "CPU Usage",       "%",  base_value=70.0, scenario="stress"),
    ]

    # inference
    inference = ONNXInferenceAdapter(threshold=0.7)
    inference.load("models/anomaly.onnx")

    # actions
    actions = {
        "log":     LogAction(action_id="log"),
        "webhook": WebhookAction(action_id="webhook", url="https://webhook.site/your-url"),
    }

    # rules
    rules = [
        Rule(
            name="high_temperature",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log", "webhook"],
            cooldown_seconds=60.0,
        ),
    ]

    # assemble and start
    exporter  = PrometheusExporter(port=8000)
    engine    = RuleEngine(rules=rules, actions=actions)
    pipelines = [
        Pipeline(sensor=s, engine=engine, inference=inference, exporter=exporter)
        for s in sensors
    ]

    monitor = MonitorLoop(pipelines=pipelines, poll_interval_seconds=2.0, exporter=exporter)
    monitor.start()


if __name__ == "__main__":
    main()
```