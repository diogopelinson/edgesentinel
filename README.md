# edgesentinel

> Intelligent observability for Linux embedded devices — reads hardware sensors, processes camera streams with YOLO, detects anomalies with ML, and streams everything to Grafana in real time.

---

## What is edgesentinel?

edgesentinel is a **monitoring platform for embedded devices** (Raspberry Pi, Orange Pi, SBCs in general) that solves a common problem: hardware monitoring tools and ML tools live in separate worlds.

- Hardware tools (`psutil`, `gpiozero`) read sensors but don't understand ML
- ML tools (`tflite`, `onnxruntime`) run models but don't monitor hardware

edgesentinel brings both together in a cohesive, observable, and extensible system.

---

## Why use it?

**Without edgesentinel**, monitoring a Raspberry Pi with a camera means gluing multiple tools with bash scripts, managing conflicting dependencies, and reinventing the wheel each project.

**With edgesentinel**, you declare what you want to monitor in a `config.yaml`:

```yaml
rules:
  - name: server_overheating
    condition:
      sensor_id: cpu_temp
      operator: ">"
      threshold: 80.0
    actions: [log, webhook]
    cooldown_seconds: 60
```

Temperature above 80°C → alert fires → webhook sent → data in Grafana. No code, no scripts.

---

## What it does

### Hardware sensor reading

Reads directly from Linux pseudo-filesystems — no heavy dependencies:

- **CPU temperature** via `/sys/class/thermal` or `vcgencmd` (Raspberry Pi)
- **CPU usage** calculated from `/proc/stat` tick differences
- **Memory usage** via `MemAvailable` from `/proc/meminfo`

### Camera streams with MediaMTX

**MediaMTX** is an RTSP stream hub. The camera connects once and the hub distributes to as many consumers as needed — edgesentinel, VLC, browser, other systems — without limiting the camera.

```
IP Camera ──▶ MediaMTX ──▶ edgesentinel (YOLO 1fps)
                     ├──▶ VLC (live viewing)
                     └──▶ Smart Incident Management
```

This solves a real problem: cheap IP cameras accept only 1-2 simultaneous connections.

### Containerized AI Inference Service

A FastAPI microservice that exposes ML models via HTTP. edgesentinel sends a frame and receives detections back. Any system can use the same endpoint.

- **YOLO** for object detection in camera frames
- **ONNX** for anomaly models that follow the edgesentinel contract — raw sensor value in, `anomaly_score` out (see [ONNX anomaly model](#onnx-anomaly-model))
- **Plug-and-play** — new model is one block in `models.yaml`, no code changes

### Rule Engine

Evaluates rules on every sensor reading with configurable operators:

| Operator | When it fires |
|---|---|
| `>` `<` `>=` `<=` `==` | simple numeric comparison |
| `anomaly` | ML model score above threshold |

Every rule has a **severity** — `info`, `warning` (default) or `critical`. It sets the log level and reaches every action of the rule, so the same sensor can have a warning at 75 °C and a critical alert at 85 °C. An invalid severity in the YAML fails when the config is loaded, not on the first firing.

### Event history

Every rule that fires becomes a row in a local SQLite file (`data/events.db`): rule, sensor, value, severity, reading time and anomaly score. No server and no new dependency — standard library only.

Recording never delays monitoring. Reading a sensor only enqueues the event, and a dedicated thread writes in batches; if the disk stalls and the queue fills up, the event is dropped with a warning, because losing one history row is better than delaying the next alert. On shutdown, Ctrl+C included, whatever is queued is written before exiting. Events older than the configured retention are removed at startup.

The history is queried from the terminal with `edgesentinel events` — see [Query the event history](#query-the-event-history).

### Incident lifecycle

A rule in alarm for an hour is one problem, not one alert per reading. The first firing opens an **incident**, every later firing of the same rule joins it, and the incident closes on its own when the sensor comes back.

| State | What it means |
|---|---|
| `triggered` | open and alerting on every firing |
| `acknowledged` | someone is on it: the history keeps recording, the actions stop repeating |
| `resolved` | the sensor came back past the margin; the next firing opens a new incident |

Closing does not happen at the threshold that opened it. A rule firing above 80 °C resolves at 72 °C — the threshold minus a **10% hysteresis margin** — so a value oscillating on the edge does not open and close an incident on every reading. Any rule can name its own closing point with `resolve_threshold`, and a value on the alarm side of the threshold fails when the config is loaded, because it would close the incident with the sensor still over the limit.

Incidents live in the same SQLite file as the events, and every event carries the `incident_id` of the episode it belongs to. Two things follow from keeping them there instead of in memory: the lifecycle survives a restart with no loading step, since the engine reads the open incidents on every evaluation; and an acknowledgement made by another process is seen on the next cycle.

### OpenTelemetry observability

Both edgesentinel and the AI Service export metrics via OTel to the same Collector. Prometheus scrapes and Grafana plots everything in real time — two services, one dashboard.

### Configurable actions

- **`log`** — structured log at the rule's severity level (`info` → INFO, `warning` → WARNING, `critical` → CRITICAL)
- **`webhook`** — HTTP POST with full JSON payload
- **`gpio_write`** — triggers GPIO pin (LED, relay, buzzer)

Which actions a rule triggers can be set on the rule itself or once per severity:

```yaml
default_actions:            # for rules that do not declare `actions`
  warning:  [log, webhook]
  critical: [log, webhook, buzzer]
```

A rule's own `actions` list replaces the default rather than adding to it, and `actions: []` dispatches nothing while the event is still recorded in the history. Unknown severities and malformed lists fail when the config is loaded.

---

## Architecture

edgesentinel uses **Hexagonal Architecture (Ports & Adapters)**. The core domain doesn't know about Prometheus, GPIO, or YOLO — only abstract contracts.

```
┌─────────────────────────────────────────────────┐
│                    core/                         │
│  ports.py     → abstract contracts              │
│  entities.py  → immutable dataclasses           │
│  rules.py     → Rule, Condition, Severity       │
│  incidents.py → Incident, IncidentState         │
└───────────────────────┬─────────────────────────┘
                        │ everything depends on core
┌───────────────────────▼─────────────────────────┐
│                 application/                     │
│  engine.py    → evaluates rules, dispatches     │
│  pipeline.py  → sense → infer → act per sensor  │
│  monitor.py   → async loop with graceful shutdown│
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│                  adapters/                       │
│  sensors/     → hardware, camera, simulated      │
│  inference/   → dummy, onnx, tflite, remote      │
│  actions/     → log, webhook, gpio               │
│  exporter/    → legacy Prometheus + OTel         │
│  store/       → events and incidents (SQLite)    │
│  state/       → cooldowns (Redis later)          │
└─────────────────────────────────────────────────┘
```

---

## Full stack

```
RTSP Camera
      │
      ▼
MediaMTX  :8554 :8888 :8889
      │
  ┌───┴──────────────────┐
  │                       │
  ▼                       ▼
edgesentinel          VLC / browser
  │
  ▼
AI Inference Service  :8080
  │
  ▼
OTel Collector  :4317
  │
  ▼
Prometheus  :9090  ──▶  Grafana  :3000
```

---

## Installation

### Requirements

| Item | Minimum | Recommended |
|---|---|---|
| Python | 3.10+ | 3.11+ |
| OS | Linux (SBC) | Raspberry Pi 4 2GB+ |
| Docker | 24+ | 28+ |

> **Windows / Mac**: use simulation mode for development without hardware.

### Install the package

```bash
pip install edgesentinel            # base
pip install edgesentinel[onnx]      # + ONNX model
pip install edgesentinel[camera]    # + camera and local YOLO
pip install edgesentinel[gpio]      # + GPIO (Raspberry Pi)
pip install edgesentinel[otel]      # + OpenTelemetry
pip install edgesentinel[all]       # everything
```

### Check your environment

```bash
edgesentinel doctor
```

---

## Configuration

```yaml
edgesentinel:
  poll_interval_seconds: 5

  sensors:
    - id: cpu_temp
      type: cpu_temperature
    - id: cpu_usage
      type: cpu_usage
    - id: memory_usage
      type: memory_usage

  cameras:
    - sensor_id: camera_01
      source: "rtsp://localhost:8554/camera_01"
      name: "Entrance Camera"
      fps_limit: 1.0
      simulated: false

  inference:
    enabled: true
    backend: onnx
    model_path: models/anomaly.onnx

  # simple mode: Prometheus scrapes directly from :8000/metrics
  exporter:
    port: 8000
    use_otel: false

  # advanced mode: send to OTel Collector, export to any backend
  # exporter:
  #   use_otel: true
  #   backend: otlp
  #   endpoint: "http://localhost:4317"
  #   service_name: "edgesentinel"

  # local history — enabled by default, even without this block
  event_store:
    enabled: true
    path: data/events.db
    retention_days: 30          # must be > 0

  # actions per severity, for rules that do not declare `actions`
  default_actions:
    warning:  [log, webhook]
    critical: [log, webhook, buzzer]

  # severity: info | warning | critical  (default: warning)
  rules:
    - name: high_temperature          # → log, webhook
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 75.0
      severity: warning
      cooldown_seconds: 60

    - name: critical_temperature      # → log, webhook, buzzer
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 85.0
        resolve_threshold: 80.0     # incident closes here; default is 10% below
      severity: critical
      cooldown_seconds: 30

    - name: person_detected           # → log only: its own list wins
      condition:
        sensor_id: camera_01
        operator: anomaly
      severity: info
      actions: [log]
      cooldown_seconds: 30

  actions:
    - id: log
      type: log
    - id: webhook
      type: webhook
      url: "https://hooks.example.com/alert"
    - id: buzzer
      type: gpio_write              # GPIO pin 17
```

---

## Running

### Start the infrastructure

```bash
cd infra/docker
docker compose up -d
docker compose ps
```

| Service | Port | Role |
|---|---|---|
| MediaMTX | 8554 / 8888 | Camera stream hub |
| AI Inference Service | 8080 | YOLO and ONNX via HTTP |
| OTel Collector | 4317 | Receives metrics from all services |
| Prometheus | 9090 | Stores time series |
| Grafana | 3000 | Real-time dashboard |

### Run edgesentinel

```bash
# real hardware
edgesentinel run --config config.yaml

# simulation (Windows / Mac)
edgesentinel simulate --scenario stress --interval 1
edgesentinel simulate --scenario normal
edgesentinel simulate --scenario spike
```

### Query the event history

```bash
edgesentinel events                                   # 20 most recent
edgesentinel events --severity critical --last 24h    # critical in the last 24 hours
edgesentinel events --rule alta_temperatura -n 50
edgesentinel events --sensor cpu_temp --json | jq .value
```

```
QUANDO               SEVERIDADE  REGRA                SENSOR        VALOR  SCORE
2026-09-17 00:35:10  WARNING     uso_alto_cpu         cpu_usage  92.36 %    0.98
2026-09-17 00:35:10  CRITICAL    temperatura_critica  cpu_temp   85.93 °C   0.96
2026-09-17 00:35:10  WARNING     alta_temperatura     cpu_temp   85.93 °C   0.96
2026-09-17 00:35:10  WARNING     uso_alto_cpu         cpu_usage  93.04 %    0.98

4 evento(s) — mostrando os 4 mais recentes; use --limit para ver mais
```

| Option | Effect |
|---|---|
| `-s, --severity info\|warning\|critical` | only that level |
| `--sensor ID` | only that sensor |
| `-r, --rule NAME` | only that rule |
| `--last 30m\|24h\|7d` | window ending now (`s`, `m`, `h`, `d`) |
| `-n, --limit N` | at most N events, newest first (default 20) |
| `--json` | one JSON object per line, with an ISO `time` field |
| `-c, --config PATH` | config whose `event_store.path` is read |

The command only reads: it never prunes old events and never creates the database. Data goes to stdout and status messages to stderr, so `--json` is safe to pipe. Exit code 0 covers results, no matches and no history yet; 1 means a bad config, a disabled store or an unreadable file; 2 is an invalid option.

### Diagnose your environment

```bash
edgesentinel doctor
```

---

## Setting up Grafana from scratch

### 1. Open Grafana

Go to `http://localhost:3000` — login `admin` / `edgesentinel`.

### 2. Add Prometheus as a datasource

1. Side menu → **Connections** → **Data sources** → **Add data source**
2. Select **Prometheus**
3. URL: `http://prometheus:9090`
4. Click **Save & test** — should show "Successfully queried the Prometheus API"

### 3. Import the dashboard

1. Side menu → **Dashboards** → **Import**
2. Click **Upload dashboard JSON file**
3. Select `dashboards/edgesentinel_dashboard_v2.json`
4. Under **Prometheus**, select the datasource created in the previous step
5. Click **Import**

### 4. Verify data

Leave edgesentinel running and click **Refresh** on the dashboard. Panels should show data within 10 seconds.

> **Tip**: after any customization, export the dashboard via **Export → Save to file** and commit it to the repository — this way you never lose it when recreating containers.

---

## Simulation mode

| Scenario | What happens |
|---|---|
| `normal` | Stable values, no rules fire |
| `stress` | Temperature ramps up until alerts fire |
| `spike` | Sudden spikes every ~20 seconds |

```
[tick 023]
  CPU Temperature   74.98 °C
  CPU Usage         90.68 %
  Memory Usage      64.50 %

[WARNING] Rule 'high_temperature' fired | sensor=cpu_temp value=75.92°C | anomaly_score=0.9366

[tick 051]
  CPU Temperature   86.12 °C
  CPU Usage         97.40 %
  Memory Usage      63.10 %

[CRITICAL] Rule 'critical_temperature' fired | sensor=cpu_temp value=86.12°C | anomaly_score=0.9366
```

In the `stress` scenario the temperature crosses 85 °C around the 50-second mark and the `critical` rule from the example config fires. `high_temperature` does not repeat there because it is still inside its 60 s cooldown.

Simulation records history just like `run` mode; the database path is printed at the start of the output, on the `Eventos :` line.

---

## AI Inference Service

### Checking

```bash
curl http://localhost:8080/health
# {"status":"ok","models":1}

curl http://localhost:8080/models
# [{"id":"yolo_v8n","type":"yolo","status":"loaded"}]
```

### Adding models

Edit `ai-inference-service/models.yaml` and restart:

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
```

`weights/` inside the container is the repository's `models/` directory, mounted by Docker Compose. A new weight file goes in `models/`.

---

## ONNX anomaly model

```bash
pip install scikit-learn skl2onnx
python scripts/train_model.py            # --seed N for a different training set
# generates: models/anomaly.onnx
```

The model is a single self-contained file with a fixed contract: the raw sensor value goes in, and an `anomaly_score` in [0, 1] comes out. Normalisation and the scoring rule live inside it, so the agent and the AI Inference Service only read that output and cannot disagree.

| Reading | Score |
|---|---|
| inside the training range (~51–65 °C) | IsolationForest, rescaled to 0 – 0.8 |
| outside the training range | from 0.8 towards 1, rising with the distance to the range |

The two parts exist because IsolationForest alone cannot tell 75 °C from 95 °C: its trees only split inside the range they were trained on, so every value past the edge ends in the same leaf and gets the same score. With the rule above the reference model gives 0.91 at 75 °C, 0.96 at 85 °C and 0.98 at 95 °C, while 58 °C scores 0.12. Models exported by earlier versions of the script lack the `anomaly_score` output and are rejected at load time; train them again.

Model files are not versioned — a fresh clone has none. [`models/README.md`](models/README.md) lists each file, how to get it and what uses it.

---

## Exposed metrics

### edgesentinel

| Prometheus metric | Type | Description |
|---|---|---|
| `edgesentinel_sensor_value` | Gauge | Current sensor value |
| `edgesentinel_anomaly_score` | Gauge | Model score (0.0 – 1.0) |
| `edgesentinel_anomaly_total` | Counter | Total anomalies detected |
| `edgesentinel_pipeline_latency_seconds` | Histogram | Full cycle time per sensor |
| `edgesentinel_inference_latency_seconds` | Histogram | ML inference time |

### AI Inference Service

| Prometheus metric | Type | Description |
|---|---|---|
| `ai_service_inference_total` | Counter | Total inferences |
| `ai_service_inference_latency_ms_milliseconds` | Histogram | Latency per inference |
| `ai_service_detections_total` | Counter | Total detections |

> These are the exact names as they appear in Prometheus and Grafana. Use them verbatim in PromQL queries.

---

## Tests

```bash
pip install pytest pytest-mock pytest-cov
pytest tests/ -v
pytest tests/ --cov=. --cov-report=term-missing
```

**353 tests, zero failures.**

| Layer | Coverage |
|---|---|
| `core/` | 100% |
| `application/engine` | 100% |
| `application/pipeline` | 100% |
| `adapters/actions/log` | 100% |
| `adapters/inference/dummy` | 100% |
| `config/mapper` | 100% |
| `adapters/state/memory` | 100% |
| `cli/events` | 99% |
| `config/loader` | 95% |
| `adapters/store/sqlite` | 94% |

---

## Project structure

```
edgesentinel/
├── core/                       # pure domain — zero external dependencies
├── config/                     # YAML loader and schema
├── adapters/
│   ├── sensors/                # cpu_temp, cpu_usage, memory, camera, simulated
│   ├── inference/              # dummy, onnx, tflite, remote (AI Service)
│   ├── actions/                # log, webhook, gpio
│   ├── exporter/               # legacy Prometheus + OpenTelemetry
│   ├── store/                  # SQLite: events and incidents
│   └── state/                  # cooldowns (in-memory; Redis later)
├── application/                # RuleEngine, Pipeline, MonitorLoop
├── cli/                        # run / simulate / doctor / events
├── ai-inference-service/       # FastAPI with containerized YOLO/ONNX
├── scripts/                    # train_model.py
├── infra/docker/               # docker-compose, MediaMTX, OTel, Prometheus, Grafana
├── dashboards/                 # edgesentinel_dashboard_v2.json for Grafana
├── data/                       # events.db — created at runtime, not tracked
└── tests/                      # unit + integration (353 tests)
```

---

## Design decisions

**Hexagonal Architecture** — the core doesn't know about infrastructure. Swapping Prometheus for Datadog is a new adapter. Swapping ONNX for TFLite is one config line.

**Direct `/proc` reading** — no `psutil`. Lighter, more explicit, no compiled C dependency.

**Lazy hardware discovery** — no sensor touches hardware in its constructor. A missing device is reported through `is_available()`, never by raising. The same `config.yaml` starts on a Raspberry Pi and on a laptop: unavailable sensors are skipped with a warning, and the rest of the monitoring carries on.

**`frozen=True` on entities** — the loop is async. Immutability eliminates concurrency bugs.

**Cooldowns behind a port** — the engine never reads a clock. It asks the `StatePort` to take a key for N seconds, and taking it is the same operation as checking it, so two pipeline threads cannot fire the same rule at once. `InMemoryState` implements that with `time.monotonic()`, because the wall clock can go backwards under NTP; the Redis adapter will let the server expire the key instead. That is the point of the port: a monotonic clock's epoch is per process, so an engine comparing timestamps could never have its cooldowns made distributed.

**Incidents with a resolution margin** — grouping firings is only half of it; an incident that never closes would have to be closed by hand, and one that closes at the threshold it opened at would flap with the sensor. Resolving 10% past the threshold, away from the alarm, is what makes the grouping usable without an operator, and `resolve_threshold` gives any rule its own point when 10% is the wrong distance.

**One open incident per rule, enforced by the database** — a partial unique index (`WHERE state != 'resolved'`) guarantees it, not the engine. The engine holds no incident in memory: it reads the open ones on every evaluation, so a restart needs no loading step and an acknowledgement from the CLI lands on the next cycle. Two pipeline threads racing to open the same incident are refused by the index, and the refusal is logged and swallowed — like a history failure, it must not silence the alert.

**Separate AI Service** — fault isolation. If YOLO crashes, sensor monitoring keeps running.

**Scoring rule inside the model file** — the agent and the AI Service are built and deployed separately and cannot share code. Putting normalisation and scoring into the ONNX graph leaves both with one job, reading `anomaly_score`, so there is a single place where the score is defined and a single place to fix it.

**History behind a queue and a writer thread** — pipelines run on a bounded thread pool, and on an SD card a single `fsync` can stall for hundreds of milliseconds. Writing directly would hold the thread that reads sensors; enqueueing does not. For the same reason, a history failure is logged and swallowed: the alert always goes out.

**MediaMTX** — cheap IP cameras accept 1-2 connections. The hub distributes to N consumers without limiting the camera.

**OpenTelemetry** — instrument once, export anywhere. No coupling to Prometheus.

---

## Roadmap

- [ ] Redis for distributed state in multi-device deployments
- [ ] gRPC in the AI Service as an alternative to HTTP
- [ ] Additional sensors: GPIO input, I2C, SPI, BME280
- [ ] Terraform for cloud-assisted deployments

Current version: **0.3.0** (`edgesentinel --version`). What changed in each release is in [CHANGELOG.md](CHANGELOG.md); the full backlog, with dependencies and delivery status per feature, is in [docs/roadmap.json](docs/roadmap.json).

---

## License

MIT