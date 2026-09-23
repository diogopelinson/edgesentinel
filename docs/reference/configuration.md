# Configuration

Everything lives under one root key, `edgesentinel:`, in a file the CLI reads
from `config.yaml` unless `--config` says otherwise. Anything the loader does
not accept fails at startup with the offending value named — the agent never
starts half-configured.

```yaml
edgesentinel:
  poll_interval_seconds: 5
  sensors: [...]
  rules: [...]
  actions: [...]
  default_actions: {...}
  inference: {...}
  exporter: {...}
  event_store: {...}
  cameras: [...]
  yolo: {...}
```

`sensors`, `rules` and `actions` are required; every other block has defaults.

## Top level

| Field | Default | Meaning |
|---|---|---|
| `poll_interval_seconds` | `5.0` | Seconds between rounds of sensor reads |

## `sensors`

A list. Each entry needs `id` and `type`; a missing one fails the load.

```yaml
sensors:
  - id: cpu_temp
    type: cpu_temperature
  - id: cpu_usage
    type: cpu_usage
  - id: memory_usage
    type: memory_usage
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | The name rules refer to, and the `sensor_id` label on every metric and event |
| `type` | yes | Which implementation to build: `cpu_temperature`, `cpu_usage`, `memory_usage` |

A sensor whose hardware is missing is not an error: it reports itself
unavailable, is skipped with a warning, and the rest of the agent runs. There
is no per-sensor parameter block yet — a pin number or an I2C address has
nowhere to go (`sensor-params` in [the roadmap](../roadmap.json)).

## `rules`

A list. Each entry needs `name` and `condition`.

```yaml
rules:
  - name: high_temperature
    condition:
      sensor_id: cpu_temp
      operator: ">"
      threshold: 75.0
      resolve_threshold: 70.0
    severity: warning
    cooldown_seconds: 60
    actions: [log, webhook]
    enabled: true
```

| Field | Default | Meaning |
|---|---|---|
| `name` | — | Identifies the rule in logs, events and incidents. One open incident per name |
| `condition` | — | See below |
| `severity` | `warning` | `info`, `warning` or `critical`. Sets the log level and reaches every action |
| `cooldown_seconds` | `0.0` | Minimum seconds between two firings of this rule. `0` fires on every matching reading |
| `actions` | unset | Action ids. Unset falls back to `default_actions`; `[]` dispatches nothing and still records the event |
| `enabled` | `true` | `false` keeps the rule in the file and out of the evaluation |

### `condition`

| Field | Default | Meaning |
|---|---|---|
| `sensor_id` | — | Which sensor this rule watches |
| `operator` | — | `>`, `<`, `>=`, `<=`, `==` or `anomaly` |
| `threshold` | `0.0` | The number compared against. Ignored by `anomaly` |
| `resolve_threshold` | unset | Where the incident closes. Unset means the threshold minus 10% of its absolute value, away from the alarm |

`anomaly` fires on the model's verdict rather than on a number, and needs
`inference.enabled: true`.

The loader refuses a `resolve_threshold` that is:

- **on the alarm side of the threshold** — `> 85` resolving at `90` would close the incident with the sensor still too hot;
- **on `==` or `anomaly`** — neither has a numeric edge for a margin to sit on;
- **not a number.**

## `actions`

A list of action definitions, referenced by rules through their `id`. Each
entry needs `id` and `type`.

```yaml
actions:
  - id: log
    type: log
  - id: webhook
    type: webhook
    url: "https://hooks.example.com/alert"
  - id: buzzer
    type: gpio_write
```

| Type | Extra fields | What it does |
|---|---|---|
| `log` | — | Writes a structured line at the rule's severity level |
| `webhook` | `url` | HTTP POST with the rule, the reading, the score and the severity |
| `gpio_write` | — | Drives a GPIO pin |

Two current limits worth knowing. `gpio_write` always uses **BCM pin 17**: the
pin is not configurable from YAML yet. And a `url` is stored in plain text —
see [SECURITY.md](../../SECURITY.md) before putting a token in one.

## `default_actions`

Which actions run for rules that declare none. Keys are severities.

```yaml
default_actions:
  warning:  [log, webhook]
  critical: [log, webhook, buzzer]
```

A rule's own `actions` list **replaces** this rather than adding to it. The
loader refuses an unknown severity, the same severity written twice in
different cases, and a value that is not a list of ids.

## `inference`

```yaml
inference:
  enabled: true
  backend: onnx
  model_path: models/anomaly.onnx
```

| Field | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Off means no scoring, and `anomaly` rules never fire |
| `backend` | `dummy` | `dummy`, `onnx`, `tflite` or `remote` |
| `model_path` | unset | The model file, for local backends |
| `service_url` | `http://localhost:8080` | The AI Service, for `remote` |
| `model_id` | unset | Which model the service should use |

Every reading is scored, including sensors the model was never trained on —
see the gotcha in [Train an anomaly model](../how-to/train-an-anomaly-model.md).

## `exporter`

```yaml
exporter:
  port: 8000
  use_otel: false
```

| Field | Default | Meaning |
|---|---|---|
| `port` | `8000` | Where `/metrics` is served |
| `use_otel` | `false` | `true` sends to an OTel Collector instead of serving Prometheus directly |
| `backend` | `prometheus` | With OTel on: `otlp` |
| `endpoint` | `http://localhost:4317` | The Collector |
| `service_name` | `edgesentinel` | The name the Collector labels this agent with |

The endpoint is unauthenticated in either mode.

## `event_store`

```yaml
event_store:
  enabled: true
  path: data/events.db
  retention_days: 30
```

| Field | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` turns off the history and the incidents with it |
| `path` | `data/events.db` | The SQLite file. Its directory is created on start |
| `retention_days` | `30.0` | Events older than this are removed at startup. Must be greater than zero |

`retention_days: 0` fails the load rather than silently deleting everything.
See [Database](database.md) for the schema.

## `cameras` and `yolo`

```yaml
cameras:
  - sensor_id: camera_01
    source: "rtsp://localhost:8554/camera_01"
    name: "Entrance Camera"
    fps_limit: 1.0
    simulated: false

yolo:
  enabled: true
  model_path: models/yolov8n.pt
  target_classes: [person, car]
  confidence: 0.5
```

Each camera needs `sensor_id` and `source`. `simulated: true` generates frames
instead of opening a stream, with `simulated_mode` choosing the pattern —
useful for testing the pipeline with no camera present. Setting them up
properly is in [Connect a real camera](../how-to/connect-a-camera.md).

## What the loader refuses

In one place, because a config that fails at startup is better than one that
misbehaves at 3 a.m.:

- a YAML file with no `edgesentinel` root key;
- a sensor without `id` or `type`, a rule without `name` or `condition`, an action without `id` or `type`, a camera without `sensor_id` or `source`;
- an unknown severity, anywhere;
- `actions` written as a mapping instead of a list, or a list holding anything that is not an id;
- the same severity declared twice in `default_actions`;
- `retention_days` of zero or less;
- a `resolve_threshold` that is non-numeric, on the alarm side of the threshold, or attached to an operator with no numeric edge.
