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
- **ONNX** for any exported model (IsolationForest, classifiers, etc.)
- **Plug-and-play** — new model is one block in `models.yaml`, no code changes

### Rule Engine

Evaluates rules on every sensor reading with configurable operators:

| Operator | When it fires |
|---|---|
| `>` `<` `>=` `<=` `==` | simple numeric comparison |
| `anomaly` | ML model score above threshold |

### OpenTelemetry observability

Both edgesentinel and the AI Service export metrics via OTel to the same Collector. Prometheus scrapes and Grafana plots everything in real time — two services, one dashboard.

### Configurable actions

- **`log`** — structured log with configurable level
- **`webhook`** — HTTP POST with full JSON payload
- **`gpio_write`** — triggers GPIO pin (LED, relay, buzzer)

---

## Architecture

edgesentinel uses **Hexagonal Architecture (Ports & Adapters)**. The core domain doesn't know about Prometheus, GPIO, or YOLO — only abstract contracts.

```
┌─────────────────────────────────────────────────┐
│                    core/                         │
│  ports.py     → abstract contracts              │
│  entities.py  → immutable dataclasses           │
│  rules.py     → Rule, Condition, cooldown       │
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

  rules:
    - name: high_temperature
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 75.0
      actions: [log, webhook]
      cooldown_seconds: 60

    - name: person_detected
      condition:
        sensor_id: camera_01
        operator: anomaly
      actions: [log, webhook]
      cooldown_seconds: 30

  actions:
    - id: log
      type: log
    - id: webhook
      type: webhook
      url: "https://hooks.example.com/alert"
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
3. Select `dashboards/edgesentinel.json`
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
```

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

---

## ONNX anomaly model

```bash
pip install scikit-learn skl2onnx
python scripts/train_model.py
# generates: models/anomaly.onnx + models/scaler.onnx
```

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

**84 tests, zero failures.**

| Layer | Coverage |
|---|---|
| `core/` | 100% |
| `application/engine` | 100% |
| `application/pipeline` | 100% |
| `adapters/inference/dummy` | 100% |
| `config/loader` | 95% |

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
│   └── exporter/               # legacy Prometheus + OpenTelemetry
├── application/                # RuleEngine, Pipeline, MonitorLoop
├── cli/                        # run / simulate / doctor
├── ai-inference-service/       # FastAPI with containerized YOLO/ONNX
├── scripts/                    # train_model.py
├── infra/docker/               # docker-compose, MediaMTX, OTel, Prometheus, Grafana
├── dashboards/                 # edgesentinel.json for Grafana
└── tests/                      # unit + integration (84 tests)
```

---

## Design decisions

**Hexagonal Architecture** — the core doesn't know about infrastructure. Swapping Prometheus for Datadog is a new adapter. Swapping ONNX for TFLite is one config line.

**Direct `/proc` reading** — no `psutil`. Lighter, more explicit, no compiled C dependency.

**`frozen=True` on entities** — the loop is async. Immutability eliminates concurrency bugs.

**`time.monotonic()` for cooldowns** — wall clock can go backwards under NTP. Monotonic only moves forward.

**Separate AI Service** — fault isolation. If YOLO crashes, sensor monitoring keeps running.

**MediaMTX** — cheap IP cameras accept 1-2 connections. The hub distributes to N consumers without limiting the camera.

**OpenTelemetry** — instrument once, export anywhere. No coupling to Prometheus.

---

## Roadmap

- [ ] Redis for distributed state in multi-device deployments
- [ ] gRPC in the AI Service as an alternative to HTTP
- [ ] Additional sensors: GPIO input, I2C, SPI, BME280
- [ ] Terraform for cloud-assisted deployments

---

## License

MIT