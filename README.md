# Edgesentinel

> Intelligent observability for Linux embedded devices — reads hardware sensors, runs ML inference on the edge, and exposes everything to Grafana in real time.

---

## Overview

Most monitoring tools for single-board computers are either hardware-only (`psutil`, `gpiozero`) or ML-only (`tflite`, `onnxruntime`). **edgesentinel** bridges both worlds: a Python library that collects sensor data, runs lightweight anomaly detection models directly on the device, and exports structured metrics to a Prometheus + Grafana stack — with zero boilerplate.

```
Hardware (Raspberry Pi, SBCs)
        │
        ▼
  edgesentinel (Python)
  ┌──────────────────────────────────────┐
  │  sensors → inference → rule engine   │
  │               │                      │
  │        Prometheus Exporter           │
  └──────────────────────────────────────┘
        │
        ▼
   Prometheus → Grafana
```

---

## Features

- **Hardware sensor reading** — CPU temperature, CPU usage and memory usage via Linux pseudo-filesystems (`/proc`, `/sys`, `vcgencmd`)
- **Pluggable ML backends** — ONNX Runtime, TensorFlow Lite, or a built-in dummy adapter for development
- **Rule engine** — YAML-driven rules with configurable operators (`>`, `<`, `==`, `anomaly`) and cooldown support
- **Prometheus exporter** — HTTP `/metrics` endpoint with per-sensor Gauges, anomaly Counters and inference latency Histograms
- **Ready-to-import Grafana dashboard** — pre-built JSON with panels for sensor values, anomaly scores, rule triggers and P95 latencies
- **Pluggable actions** — structured logging, HTTP webhooks and GPIO write (LED, relay, buzzer)
- **Graceful shutdown** — handles `SIGINT` and `SIGTERM` for clean `systemd` integration

---

## Architecture

edgesentinel follows **Hexagonal Architecture (Ports & Adapters)**. The core domain has zero external dependencies — no Prometheus, no GPIO, no ONNX. All infrastructure lives in adapters that implement core interfaces.

```
┌─────────────────────────────────────────────┐
│                   core/                      │
│  ports.py       → abstract contracts         │
│  entities.py    → immutable dataclasses      │
│  rules.py       → Rule, Condition, cooldown  │
└────────────────┬────────────────────────────┘
                 │ depends on
┌────────────────▼────────────────────────────┐
│               application/                   │
│  engine.py    → rule evaluation + dispatch   │
│  pipeline.py  → sense → infer → act          │
│  monitor.py   → async polling loop           │
└────────────────┬────────────────────────────┘
                 │ depends on
┌────────────────▼────────────────────────────┐
│                adapters/                     │
│  sensors/     → hardware readers             │
│  inference/   → ONNX, TFLite, Dummy          │
│  actions/     → log, webhook, GPIO           │
│  exporter/    → Prometheus HTTP server       │
└─────────────────────────────────────────────┘
```

**Dependency rule:** adapters depend on application, application depends on core. Core knows nothing about the outside world. Swapping a backend (e.g. TFLite → ONNX) touches only the adapter — nothing else changes.

---

## Quick Start

### Requirements

- Python 3.10+
- Linux (Raspberry Pi, Orange Pi, or any SBC)
- Docker (optional, for Prometheus + Grafana stack)

### Installation

```bash
# base install
pip install edgesentinel

# with ONNX backend
pip install edgesentinel[onnx]

# with TFLite backend (recommended for Raspberry Pi)
pip install edgesentinel[tflite]

# with GPIO support
pip install edgesentinel[gpio]
```

### Configuration

Create a `config.yaml` file:

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

  inference:
    enabled: true
    backend: dummy        # dummy | onnx | tflite
    model_path: null      # path to .onnx or .tflite model file

  exporter:
    port: 8000

  rules:
    - name: high_temperature
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 75.0
      actions: [log]
      cooldown_seconds: 60

    - name: anomaly_detected
      condition:
        sensor_id: cpu_temp
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

### Run

```bash
edgesentinel --config config.yaml

# with debug logging
edgesentinel --config config.yaml --log-level DEBUG
```

---

## Grafana Dashboard

Import the pre-built dashboard from `dashboards/edgesentinel.json`:

1. Open Grafana → **Dashboards** → **Import**
2. Upload `edgesentinel.json`
3. Select your Prometheus data source

### Panels included

| Panel | Query |
|---|---|
| Sensor values over time | `edgesentinel_sensor_value` |
| Anomaly score | `edgesentinel_anomaly_score` |
| Anomaly rate (5m) | `rate(edgesentinel_anomaly_total[5m])` |
| Inference latency P95 | `histogram_quantile(0.95, ...)` |
| Pipeline latency P95 | `histogram_quantile(0.95, ...)` |

---

## Metrics Reference

| Metric | Type | Description |
|---|---|---|
| `edgesentinel_sensor_value` | Gauge | Current sensor reading |
| `edgesentinel_anomaly_score` | Gauge | ML model output (0.0 – 1.0) |
| `edgesentinel_anomaly_total` | Counter | Total anomalies detected |
| `edgesentinel_rule_triggered_total` | Counter | Total rule triggers |
| `edgesentinel_inference_latency_seconds` | Histogram | Per-inference duration |
| `edgesentinel_pipeline_latency_seconds` | Histogram | Full cycle duration |

All metrics include labels for `sensor_id`, `sensor_name`, and `model_id` — enabling per-sensor filtering in Grafana.

---

## Supported Sensors

| Type | Source | Notes |
|---|---|---|
| `cpu_temperature` | `/sys/class/thermal` or `vcgencmd` | Auto-detects Raspberry Pi |
| `cpu_usage` | `/proc/stat` | Calculated from tick diff |
| `memory_usage` | `/proc/meminfo` | Uses `MemAvailable`, not `MemFree` |

New sensors implement `SensorPort` from `core/ports.py` and register in `adapters/sensors/registry.py` — one file, one line.

---

## ML Backends

| Backend | Install | Use case |
|---|---|---|
| `dummy` | built-in | Development, testing, no model needed |
| `onnx` | `pip install edgesentinel[onnx]` | scikit-learn, PyTorch exported models |
| `tflite` | `pip install edgesentinel[tflite]` | Optimized for Raspberry Pi ARM builds |

The model contract is simple: input is a normalized 1D float array, output is a score in `[0.0, 1.0]`. Any framework that exports to ONNX or TFLite is compatible.

---

## Running Tests

```bash
pip install pytest pytest-mock pytest-cov
pytest tests/ -v
pytest tests/ --cov=. --cov-report=term-missing
```

### Coverage summary

| Layer | Coverage |
|---|---|
| `core/` | 100% |
| `config/` | 95%+ |
| `application/engine` | 100% |
| `adapters/inference/dummy` | 100% |
| `adapters/sensors/memory` | 100% |
| `adapters/actions/log` | 100% |

Infrastructure adapters (`gpio`, `onnx`, `tflite`, `prometheus`) require ARM hardware or unavailable libs on non-Linux systems — coverage zero is expected in development environments.

---

## Project Structure

```
edgesentinel/
├── core/
│   ├── ports.py          # abstract contracts — SensorPort, InferencePort, ActionPort
│   ├── entities.py       # immutable dataclasses — SensorReading, AnomalyScore
│   └── rules.py          # Rule, Condition with cooldown support
├── config/
│   ├── schema.py         # dataclasses mirroring YAML structure
│   ├── loader.py         # YAML → EdgeSentinelConfig
│   └── mapper.py         # EdgeSentinelConfig → core domain objects
├── adapters/
│   ├── sensors/          # cpu_temperature, cpu_usage, memory_usage
│   ├── inference/        # dummy, onnx, tflite
│   ├── actions/          # log, webhook, gpio_write
│   └── exporter/         # Prometheus HTTP exporter
├── application/
│   ├── engine.py         # RuleEngine — evaluates rules, dispatches actions
│   ├── pipeline.py       # sense → infer → act per sensor
│   └── monitor.py        # async polling loop with graceful shutdown
├── cli/
│   ├── builder.py        # assembles all components from config
│   └── main.py           # CLI entry point
└── dashboards/
    └── edgesentinel.json # importable Grafana dashboard
```

---

## Design Decisions

**Why Hexagonal Architecture?**
Sensors, ML backends, and exporters are all interchangeable without touching business logic. Adding a new sensor is one new file implementing `SensorPort`. Swapping ONNX for TFLite is one config line change.

**Why read `/proc` directly instead of `psutil`?**
`psutil` is a large dependency. On a device with limited storage, reading `/proc/stat` and `/proc/meminfo` directly keeps the footprint minimal and the code explicit about what it reads.

**Why `frozen=True` on entities?**
The monitor loop is async — `SensorReading` objects travel across multiple coroutines. Immutability eliminates shared-state bugs entirely.

**Why `time.monotonic()` for cooldowns and latency?**
Wall clock (`time.time()`) can jump backward on NTP sync. Monotonic clock only moves forward — correct for measuring intervals.

**Why a dummy ML backend?**
The full pipeline — sensors, rules, Prometheus, Grafana — is demonstrable from day one without a trained model. The ML backend slots in later without changing anything else.

---

## License

MIT