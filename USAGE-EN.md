# Usage guide — edgesentinel

This guide covers how to use edgesentinel as a library, how to connect real cameras via MediaMTX, how the AI Inference Service works in practice, and how to configure Prometheus and Grafana from scratch.

---

## Table of contents

1. [CLI usage](#1-cli-usage)
2. [Library usage](#2-library-usage)
3. [Connecting real cameras with MediaMTX](#3-connecting-real-cameras-with-mediamtx)
4. [AI Inference Service in practice](#4-ai-inference-service-in-practice)
5. [Configuring Prometheus and Grafana](#5-configuring-prometheus-and-grafana)
6. [Creating your own sensor](#6-creating-your-own-sensor)
7. [Creating your own action](#7-creating-your-own-action)
8. [Interface reference](#8-interface-reference)

---

## 1. CLI usage

### Check your environment

```bash
edgesentinel doctor
```

Shows what is available on your system — Python, dependencies, sensors, models, cameras and the exporter port.

### Run with real hardware

```bash
edgesentinel run --config config.yaml
edgesentinel run --config config.yaml --log-level DEBUG
```

### Simulate without hardware (Windows / Mac)

```bash
edgesentinel simulate --scenario normal
edgesentinel simulate --scenario stress --interval 1
edgesentinel simulate --scenario spike
```

### Event history

Both `run` and `simulate` record every fired rule in `data/events.db` (SQLite), with a 30-day retention. The path and retention are set in the `event_store` block of `config.yaml`, and `enabled: false` turns history off. To query it from Python, see [Querying the history](#querying-the-history).

### Incidents

The same run also records incidents. The first firing of a rule opens one, every later firing joins it, and it closes when the sensor comes back past the resolution margin — the threshold minus 10%, or `resolve_threshold` when the rule names its own point. Events and incidents share the database, and each event carries the `incident_id` of the episode it belongs to.

There is no `edgesentinel incidents` command yet — listing and acknowledging from the terminal is its own entry in [docs/roadmap.json](docs/roadmap.json). Until then SQLite answers directly:

```bash
# what is open right now
sqlite3 data/events.db "SELECT incident_id, rule_name, state, \
    datetime(opened_at, 'unixepoch', 'localtime') AS opened \
    FROM incidents WHERE state != 'resolved' ORDER BY opened_at;"

# how many firings each episode grouped
sqlite3 data/events.db "SELECT i.incident_id, i.rule_name, COUNT(e.event_id) AS firings \
    FROM incidents i LEFT JOIN events e ON e.incident_id = i.incident_id \
    GROUP BY i.incident_id ORDER BY firings DESC;"

# acknowledge one by hand: the history keeps recording, the actions stop repeating
sqlite3 data/events.db "UPDATE incidents SET state = 'acknowledged', \
    acknowledged_at = strftime('%s', 'now') WHERE incident_id = 7;"
```

The agent picks that acknowledgement up on the next evaluation — it reads the open incidents from the database every time instead of keeping them in memory, which is also why the lifecycle survives a restart with no loading step.

### Query the history

```bash
# what fired in the last hour
edgesentinel events --last 1h

# only critical events from one sensor
edgesentinel events --severity critical --sensor cpu_temp

# another config (and therefore another database)
edgesentinel events --config /etc/edgesentinel/config.yaml -n 100
```

With `--json`, each line is a complete object:

```json
{"event_id": 1162, "time": "2026-09-17T00:35:10-03:00", "timestamp": 1789616110.68, "severity": "warning", "rule_name": "uso_alto_cpu", "sensor_id": "cpu_usage", "value": 92.36, "unit": "%", "anomaly_score": 0.9769}
```

That makes the history easy to script (Linux / macOS):

```bash
# firings per rule over the last 24 hours
edgesentinel events --last 24h --limit 100000 --json | jq -r .rule_name | sort | uniq -c

# external alert if anything critical happened in the last 5 minutes
if edgesentinel events --severity critical --last 5m --json | grep -q .; then
    echo "recent critical"
fi
```

Three guarantees back these uses:

- **stdout holds data only.** "No events found" and errors go to stderr, so the `grep -q .` above only matches real events.
- **Querying changes nothing.** The command applies no retention and does not create the database when it is missing.
- **The exit code tells the cases apart.** `0` for results, no results or an empty history; `1` for an invalid config, a disabled store or an unreadable file; `2` for an invalid option such as `--last yesterday`.

---

## 2. Library usage

### Simplest case — load from config.yaml

```python
from config.loader import load
from cli.builder import build_monitor

config  = load("config.yaml")
monitor = build_monitor(config)
monitor.start()   # blocking — Ctrl+C shuts down cleanly
```

### Full control — assembling manually

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

### Querying the history

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

## 3. Connecting real cameras with MediaMTX

### Why MediaMTX exists

Cheap IP cameras accept only **1-2 simultaneous RTSP connections**. Without MediaMTX, if edgesentinel is connected, VLC can't open the stream. With MediaMTX:

```
Camera ──▶ MediaMTX ──▶ edgesentinel (YOLO)
                   ├──▶ VLC / browser
                   ├──▶ Smart Incident Management
                   └──▶ disk recording
```

The camera makes one connection. MediaMTX distributes to as many consumers as needed.

### Step 1 — Start MediaMTX

```bash
cd infra/docker
docker compose up -d mediamtx
docker compose ps
# mediamtx   Up   :8554 (RTSP), :8888 (HLS), :8889 (WebRTC)
```

### Step 2 — Camera publishes to MediaMTX

**Option A — Camera supports native RTSP push**

In the camera's web interface, set the stream destination to:
```
rtsp://YOUR_PC_IP:8554/camera_01
```

**Option B — Relay with FFmpeg**

```bash
# Ubuntu/Raspberry Pi: sudo apt install ffmpeg
ffmpeg -i rtsp://admin:password@192.168.1.100:554/stream \
       -c copy \
       -f rtsp rtsp://localhost:8554/camera_01
```

**Option C — Simulate with a local video**

```bash
ffmpeg -re -i test_video.mp4 \
       -c copy \
       -f rtsp rtsp://localhost:8554/camera_01
```

### Step 3 — Verify the stream

Open in VLC: `rtsp://localhost:8554/camera_01`

Or via browser (HLS): `http://localhost:8888/camera_01/index.m3u8`

### Step 4 — edgesentinel consumes from MediaMTX

```yaml
cameras:
  - sensor_id: camera_01
    source: "rtsp://localhost:8554/camera_01"   # MediaMTX, not the camera directly
    name: "Entrance Camera"
    fps_limit: 1.0     # 1fps is enough for detection — doesn't overload hardware
    simulated: false
```

### Step 5 — Multiple cameras

```yaml
cameras:
  - sensor_id: camera_entrance
    source: "rtsp://localhost:8554/camera_entrance"
    fps_limit: 1.0
    simulated: false

  - sensor_id: camera_storage
    source: "rtsp://localhost:8554/camera_storage"
    fps_limit: 0.5    # 1 frame every 2 seconds — low-risk area
    simulated: false
```

---

## 4. AI Inference Service in practice

### Endpoints

```bash
# status
curl http://localhost:8080/health
# {"status":"ok","models":2}

# loaded models
curl http://localhost:8080/models
# [{"id":"yolo_v8n","type":"yolo","status":"loaded"},...]

# inference with base64 frame
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"model_id":"yolo_v8n","frame_b64":"BASE64_HERE"}'

# inference with stream URL (captures one frame automatically)
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"model_id":"yolo_v8n","stream_url":"rtsp://localhost:8554/camera_01"}'

# sensor anomaly inference
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"model_id":"anomaly_onnx","sensor_value":85.0}'
```

**Response:**

```json
{
  "model_id": "yolo_v8n",
  "detections": [
    {"class_name": "person", "confidence": 0.91, "bbox": [120.0, 50.0, 380.0, 480.0]}
  ],
  "inference_latency_ms": 178.42,
  "has_detections": true
}
```

### Adding a model

Edit `ai-inference-service/models.yaml`:

```yaml
models:
  - id: yolo_v8n
    type: yolo
    path: weights/yolov8n.pt
    target_classes: [person, car, truck]
    confidence_threshold: 0.5

  - id: fire_detector
    type: yolo
    path: weights/fire.pt
    target_classes: [fire, smoke]
    confidence_threshold: 0.4
```

```bash
docker compose restart ai-inference-service
curl http://localhost:8080/models
# [..., {"id":"fire_detector","type":"yolo","status":"loaded"}]
```

The `weights/` paths resolve to the repository's `models/` directory, which Docker Compose mounts at `/app/weights`. So `weights/fire.pt` means the file `models/fire.pt` on the host. Weight files are never committed: `.gitignore` excludes `models/*.pt`, `models/*.onnx` and `ai-inference-service/weights/`, and [`models/README.md`](models/README.md) says how to obtain the ones the project uses.

### ONNX anomaly models

`type: onnx` models, in the AI service and in the agent (`inference.backend: onnx`), follow one contract:

| | Name | Type | Meaning |
|---|---|---|---|
| input | any | `float32 [N, 1]` | the raw sensor value, unscaled |
| output | `anomaly_score` | `float32 [N, 1]` | 0 = normal, 1 = maximally anomalous |

`scripts/train_model.py` produces such a model, with normalisation and the scoring rule built into the graph. Any other ONNX file exposing that input and output works as well. A file without an `anomaly_score` output is refused when it loads — the AI service logs the error and keeps serving the other models. A `scaler_path` left in `models.yaml` from earlier versions is ignored with a warning.

For `anomaly_onnx`, the `/predict` response carries one `anomaly` detection whose `confidence` is the `anomaly_score`, or no detection when the score is below `confidence_threshold`.

---

## 5. Configuring Prometheus and Grafana

### Two metric collection modes

**Simple mode — Prometheus scrapes edgesentinel directly**

Best for getting started. In `config.yaml`:

```yaml
exporter:
  port: 8000
  use_otel: false
```

In `infra/docker/prometheus.yml`:

```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: "edgesentinel"
    static_configs:
      - targets:
          - "host.docker.internal:8000"   # Windows/Mac
          # or "172.17.0.1:8000"          # Linux

  - job_name: "ai-service-via-otel"
    static_configs:
      - targets:
          - "edgesentinel-otel-collector:8889"
```

**Advanced mode — via OTel Collector**

To export to Grafana Cloud, Datadog or InfluxDB without changing code. In `config.yaml`:

```yaml
exporter:
  use_otel: true
  backend: otlp
  endpoint: "http://localhost:4317"
  service_name: "edgesentinel"
```

The OTel Collector receives on `:4317` and exposes to Prometheus on `:8889`. The `prometheus.yml` only points to the Collector:

```yaml
scrape_configs:
  - job_name: "edgesentinel"
    static_configs:
      - targets:
          - "edgesentinel-otel-collector:8889"
```

### Checking Prometheus

Open `http://localhost:9090/targets` — all targets should be **UP**.

To confirm metrics are coming in:

```
http://localhost:9090/api/v1/label/__name__/values
```

Should return metric names including `edgesentinel_sensor_value`.

### Setting up Grafana from scratch

**1. Open Grafana**

```
http://localhost:3000
login: admin
password: edgesentinel
```

**2. Add Prometheus as datasource**

1. Side menu → **Connections** → **Data sources**
2. Click **Add data source** → select **Prometheus**
3. URL: `http://prometheus:9090`
4. Click **Save & test**

If you see "Successfully queried the Prometheus API", it's working.

**3. Import the dashboard**

1. Side menu → **Dashboards** → **Import**
2. Click **Upload dashboard JSON file**
3. Select `dashboards/edgesentinel_dashboard_v2.json`
4. Under **Prometheus**, select the datasource from the previous step
5. Click **Import**

**4. Useful PromQL queries for building custom panels**

```promql
# current value of all sensors
edgesentinel_sensor_value

# anomaly score by sensor
edgesentinel_anomaly_score{sensor_id="cpu_temp"}

# anomaly rate over last 5 minutes
rate(edgesentinel_anomaly_total[5m])

# pipeline P95 latency
histogram_quantile(0.95, rate(edgesentinel_pipeline_latency_seconds_bucket[5m]))

# AI Service P95 latency in ms
histogram_quantile(0.95, rate(ai_service_inference_latency_ms_milliseconds_bucket[5m]))

# inference rate per second per model
rate(ai_service_inference_total[1m])
```

---

## 6. Creating your own sensor

```python
from core.ports import SensorPort
from core.entities import SensorReading


class MotorTemperatureSensor(SensorPort):
    """Reads motor temperature from a device file."""

    def __init__(self, sensor_id: str, device_path: str) -> None:
        self.sensor_id   = sensor_id
        self.device_path = device_path

    def read(self) -> SensorReading:
        with open(self.device_path) as f:
            value = float(f.read().strip()) / 1000.0

        return SensorReading(
            sensor_id=self.sensor_id,
            name="Motor Temperature",
            value=value,
            unit="°C",
        )

    def is_available(self) -> bool:
        import os
        return os.path.exists(self.device_path)
```

### Availability contract

Every sensor follows three rules, and the example above already meets all of them:

1. **`__init__` does not touch the hardware** — it only stores configuration. No opening files, probing devices or running commands in the constructor.
2. **Absence is reported through `is_available()`**, never by raising. At startup, `edgesentinel run` skips unavailable sensors with a `WARNING` and carries on with the rest; `edgesentinel doctor` lists them as unavailable. A constructor that raises sends both down their error path instead.
3. **When `read()` fails, the message says where it looked.** `"No source found. Paths tried: /sys/..., /usr/bin/..."` turns a diagnosis into a lookup.

Inheriting from `adapters.sensors.base.BaseSensor` instead of `SensorPort` gives you `is_available()` for free: it attempts a `read()` and returns `False` if the read raises.

---

## 7. Creating your own action

```python
from core.ports import ActionPort
from core.entities import ActionContext
from core.rules import Severity
import requests


ICONS = {
    Severity.INFO:     "ℹ️",
    Severity.WARNING:  "⚠️",
    Severity.CRITICAL: "🚨",
}


class TelegramAction(ActionPort):
    """Sends a Telegram message when a rule fires."""

    def __init__(self, action_id: str, token: str, chat_id: str) -> None:
        self.action_id = action_id
        self._token    = token
        self._chat_id  = chat_id

    def execute(self, context: ActionContext) -> None:
        reading  = context.reading
        score    = context.score
        severity = context.extras.get("severity", Severity.WARNING)

        text = (
            f"{ICONS[severity]} *{context.rule_name}* [{severity.value}]\n"
            f"Sensor: `{reading.sensor_id}`\n"
            f"Value: `{reading.value}{reading.unit}`"
        )

        if score and score.is_anomaly:
            text += f"\nAnomaly score: `{score.score:.2f}`"

        requests.post(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            json={"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
```

The severity of the rule that fired arrives in `context.extras["severity"]` as a `Severity`. For text, use `.value` — on Python 3.10, `str(Severity.CRITICAL)` returns `'Severity.CRITICAL'`, not `'critical'`. The `.get` default covers the action being called outside the `RuleEngine`.

---

## 8. Interface reference

### `SensorPort`

```python
class SensorPort(ABC):
    def read(self) -> SensorReading: ...
    def is_available(self) -> bool: ...
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

### `EventPort`

```python
class EventPort(ABC):
    def start(self) -> None: ...                 # constructing never touches the disk
    def append(self, event: Event) -> None: ...  # never blocks the caller
    def query(self, *, severity=None, sensor_id=None, rule_name=None,
              since=None, until=None, limit=100) -> list[Event]: ...
    def prune(self, before: float) -> int: ...   # returns how many were removed
    def close(self) -> None: ...                 # writes whatever is pending
```

### `StatePort`

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

### `IncidentPort`

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

### `SensorReading`

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

### `AnomalyScore`

```python
@dataclass(frozen=True)
class AnomalyScore:
    score: float            # 0.0 = normal, 1.0 = full anomaly
    threshold: float
    is_anomaly: bool        # score >= threshold
    model_id: str
    reading: SensorReading
```

### `ActionContext`

```python
@dataclass
class ActionContext:
    rule_name: str
    reading: SensorReading
    score: AnomalyScore | None
    extras: dict            # extras["severity"] carries the rule's Severity
```

### `Event`

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

### `Incident`

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

### `IncidentState`

```python
class IncidentState(str, Enum):
    TRIGGERED    = "triggered"      # open, alerting on every firing
    ACKNOWLEDGED = "acknowledged"   # the history keeps recording, the actions stop
    RESOLVED     = "resolved"       # closed; the next firing opens a new incident
```

There is no `normal` state. Normal is the absence of an open incident — storing it would mean a row for every rule that has never fired.

### `Rule`

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

### `Severity`

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

### Action resolution (`default_actions`)

| The rule declares | `default_actions` has the rule's severity | Actions dispatched |
|---|---|---|
| `actions: [log]` | either way | `[log]` — the rule's list, not added to the default |
| `actions: []` | either way | none — the event still goes to the history |
| nothing | yes | the `default_actions` list for that severity |
| nothing | no | none |

Rules with no actions at all are logged at `DEBUG` on the `edgesentinel.config` logger. In `config.yaml`, an unknown severity in `default_actions`, the same severity written twice (`warning` and `Warning`), a list that is not made of ids, and a rule's `actions` written as a mapping all fail at load time.

### Available operators

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