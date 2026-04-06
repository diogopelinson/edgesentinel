# edgesentinel

> Intelligent observability for Linux embedded devices — reads hardware sensors, processes camera streams with YOLO, detects anomalies with ML, and streams everything to Grafana in real time.

---

## What is edgesentinel?

edgesentinel is an **observability platform for embedded devices** (Raspberry Pi, Orange Pi, SBCs) that solves a common problem: hardware monitoring tools and ML tools live in separate worlds.

- Hardware tools (`psutil`, `gpiozero`) read sensors but know nothing about ML
- ML tools (`tflite`, `onnxruntime`) run models but don't monitor hardware

edgesentinel brings both together in a cohesive, observable and extensible system.

---

## Why use it?

**Without edgesentinel**, monitoring a Raspberry Pi with a camera means gluing multiple tools together with bash scripts, managing conflicting dependencies and reinventing the wheel for every project.

**With edgesentinel**, you declare what to monitor in a `config.yaml`:

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

## What the system does

### Hardware sensor reading

Reads directly from Linux pseudo-filesystems — no heavy dependencies:

- **CPU temperature** via `/sys/class/thermal` or `vcgencmd` (Raspberry Pi)
- **CPU usage** calculated from `/proc/stat` tick differences
- **Memory usage** via `MemAvailable` from `/proc/meminfo`

### Camera streams with MediaMTX

**MediaMTX** is an RTSP stream hub. The camera connects once and the hub distributes to as many consumers as needed — edgesentinel, VLC, browser, other systems — without limiting the camera.

```
IP Camera ──▶ MediaMTX ──▶ edgesentinel (YOLO 1fps)
                      ├──▶ VLC (live view)
                      └──▶ Smart Incident Management
```

This solves a real problem: cheap IP cameras accept only 1-2 simultaneous connections.

### Containerized AI Inference Service

A FastAPI microservice that exposes ML models via HTTP. edgesentinel sends a frame and receives detections back. Any system can use the same endpoint.

- **YOLO** for object detection in camera frames
- **ONNX** for any exported model (IsolationForest, classifiers, etc.)
- **Plug-and-play** — adding a model is one line in `models.yaml`, no code changes

### Rule Engine

Evaluates rules on every sensor reading with configurable operators:

| Operator | When it fires |
|---|---|
| `>` `<` `>=` `<=` `==` | simple numeric comparison |
| `anomaly` | ML model score above threshold |

### Observability with OpenTelemetry

edgesentinel and the AI Service export metrics via OTel to the same Collector. Prometheus collects and Grafana plots everything in real time — two services, one dashboard.

### Configurable actions

- **`log`** — structured log with configurable level
- **`webhook`** — HTTP POST with full JSON payload
- **`gpio_write`** — write to a GPIO pin (LED, relay, buzzer)

---

## Architecture

edgesentinel uses **Hexagonal Architecture (Ports & Adapters)**. The core domain knows nothing about Prometheus, GPIO or YOLO — only abstract contracts.

```
┌─────────────────────────────────────────────────┐
│                    core/                         │
│  ports.py     → abstract contracts               │
│  entities.py  → immutable dataclasses            │
│  rules.py     → Rule, Condition, cooldown        │
└───────────────────────┬─────────────────────────┘
                        │ everything depends on core
┌───────────────────────▼─────────────────────────┐
│                 application/                     │
│  engine.py    → evaluates rules, dispatches      │
│  pipeline.py  → sense → infer → act per sensor   │
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

Swapping the ML backend is one line in `config.yaml`. Adding a sensor is one Python file. Replacing Prometheus is a new adapter — no domain changes.

---

## Full stack

```
IP Camera (RTSP)
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
| System | Linux (SBC) | Raspberry Pi 4 2GB+ |
| Docker | 24+ | 28+ |

> **Windows / Mac**: use simulation mode for development without hardware.

### Install the package

```bash
pip install edgesentinel            # base
pip install edgesentinel[onnx]      # + ONNX model
pip install edgesentinel[camera]    # + camera and local YOLO
pip install edgesentinel[gpio]      # + GPIO (Raspberry Pi)
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

  # hardware sensors
  sensors:
    - id: cpu_temp
      type: cpu_temperature
    - id: cpu_usage
      type: cpu_usage
    - id: memory_usage
      type: memory_usage

  # cameras (MediaMTX as source)
  cameras:
    - sensor_id: camera_01
      source: "rtsp://localhost:8554/camera_01"
      name: "Entrance Camera"
      fps_limit: 1.0
      simulated: false

  # inference via AI Service
  inference:
    enabled: true
    backend: remote
    service_url: "http://localhost:8080"
    model_id: "yolo_v8n"
    threshold: 0.5

  # OpenTelemetry exporter
  exporter:
    use_otel: true
    backend: otlp
    endpoint: "http://localhost:4317"
    service_name: "edgesentinel"

  # alert rules
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

  # available actions
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
| OTel Collector | 4317 | Collects metrics from all services |
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

### Import the Grafana dashboard

1. Open `http://localhost:3000` → `admin` / `edgesentinel`
2. **Dashboards → Import → Upload**
3. Select `dashboards/edgesentinel.json`

---

## Simulation mode

Runs the **full pipeline** with synthetic data — ideal for development without hardware.

| Scenario | What happens |
|---|---|
| `normal` | Stable values, no rules fire |
| `stress` | Temperature ramps up until alerts fire |
| `spike` | Sudden temperature spikes every ~20 seconds |

```
[tick 023]
  CPU Temperature   74.98 °C
  CPU Usage         90.68 %
  Memory Usage      64.50 %

[WARNING] Rule 'high_temperature' fired | sensor=cpu_temp value=75.92°C | anomaly_score=0.9366
```

---

## AI Inference Service

### Verifying

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

Zero code changes.

---

## ONNX anomaly model

```bash
pip install scikit-learn skl2onnx
python scripts/train_model.py
# generates: models/anomaly.onnx + models/scaler.onnx
```

The model learns what normal operation looks like. When temperature deviates from that pattern, the score rises — with the `stress` scenario you will see scores reaching `0.93+`.

---

## Exposed metrics

### edgesentinel

| Metric | Type | Description |
|---|---|---|
| `edgesentinel.sensor.value` | Gauge | Current sensor reading |
| `edgesentinel.anomaly.score` | Gauge | ML model score (0.0 – 1.0) |
| `edgesentinel.anomaly.total` | Counter | Total anomalies detected |
| `edgesentinel.pipeline.latency` | Histogram | Full cycle time per sensor |

### AI Inference Service

| Metric | Type | Description |
|---|---|---|
| `ai_service.inference.total` | Counter | Total inferences per model |
| `ai_service.inference.latency_ms` | Histogram | Inference latency |
| `ai_service.detections.total` | Counter | Total detections per model |

---

## Tests

```bash
pip install pytest pytest-mock pytest-cov
pytest tests/ -v
pytest tests/ --cov=. --cov-report=term-missing
```

**69 tests, zero failures.**

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
└── tests/                      # unit + integration (69 tests)
```

---

## Design decisions

**Hexagonal Architecture** — the core knows nothing about infrastructure. Swapping Prometheus for Datadog is a new adapter. Swapping ONNX for TFLite is one config line.

**Direct `/proc` reading** — no `psutil`. Lighter, more explicit, no compiled C dependency.

**`frozen=True` on entities** — the loop is async. Immutability eliminates concurrency bugs.

**`time.monotonic()` for cooldowns** — wall clock can go backward on NTP sync. Monotonic clock only moves forward.

**AI Service separated** — failure isolation. If YOLO crashes, sensor monitoring continues. Other systems use the same endpoint.

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
