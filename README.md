# edgesentinel

> Intelligent observability for Linux embedded devices — reads hardware sensors, detects anomalies with ML, and streams everything to Grafana in real time.

---

## What is this?

Most tools for Raspberry Pi and SBCs are either **hardware-only** (`psutil`, `gpiozero`) or **ML-only** (`tflite`, `onnxruntime`). `edgesentinel` bridges both worlds:

- Reads CPU temperature, usage and memory directly from Linux pseudo-filesystems
- Runs an anomaly detection model **on the device itself**
- Exports metrics to Prometheus and plots them in Grafana in real time
- Fires alerts via log, webhook or GPIO when something goes wrong

All configured with a single `config.yaml` file and zero boilerplate.

---

## How it works

```
Raspberry Pi / SBC
      │
      ▼
edgesentinel reads sensors every N seconds
      │
      ├─ ML model scores the reading (0.0 → 1.0)
      │
      ├─ rule engine checks config.yaml rules
      │
      ├─ actions fire (log, webhook, GPIO)
      │
      └─ /metrics exposed on port 8000
            │
            ▼
      Prometheus scrapes every 5s
            │
            ▼
      Grafana plots in real time
```

---

## Installation

### Requirements

- Python 3.10+
- Linux (Raspberry Pi, Orange Pi, or any SBC)
- Docker (optional — for Prometheus + Grafana)

### Install the package

```bash
# base install
pip install edgesentinel

# with ONNX backend (scikit-learn, PyTorch models)
pip install edgesentinel[onnx]

# with TFLite backend (lighter, recommended for Raspberry Pi)
pip install edgesentinel[tflite]

# with GPIO support (LED, relay, buzzer)
pip install edgesentinel[gpio]
```

### Check your environment

```bash
edgesentinel doctor
```

This command inspects your environment and reports what is available:

```
edgesentinel doctor
====================================================
Python
  OK      Python 3.11.2

Dependencies
  OK      pyyaml 6.0.3
  OK      prometheus-client 0.24.1
  OK      numpy 1.26.4
  WARN    tflite-runtime — not installed (optional)

Sensors
  OK      cpu_temperature      62.5 °C
  OK      cpu_usage            34.1 %
  OK      memory_usage         48.3 %

Inference backends
  OK      dummy      available
  OK      onnx       available

Exporter
  OK      port 8000 is free
====================================================
All good — system ready to run.
```

---

## Configuration

Create a `config.yaml` file at the project root:

```yaml
edgesentinel:
  poll_interval_seconds: 5       # how often to read sensors

  sensors:
    - id: cpu_temp
      type: cpu_temperature
    - id: cpu_usage
      type: cpu_usage
    - id: memory_usage
      type: memory_usage

  inference:
    enabled: true
    backend: onnx                # dummy | onnx | tflite
    model_path: models/anomaly.onnx

  exporter:
    port: 8000                   # Prometheus will scrape this port

  rules:
    - name: high_temperature
      condition:
        sensor_id: cpu_temp
        operator: ">"            # available operators: > < >= <= == anomaly
        threshold: 75.0
      actions: [log, webhook]
      cooldown_seconds: 60       # won't fire again for 60s

    - name: anomaly_detected
      condition:
        sensor_id: cpu_temp
        operator: anomaly        # uses the ML model score
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

### On real hardware (Raspberry Pi / SBC)

```bash
edgesentinel run --config config.yaml
```

### Simulating on Windows / Mac (no hardware needed)

The `simulate` mode runs the full pipeline with synthetic data. You can watch rules firing, logs appearing and metrics flowing into Grafana — all without hardware.

```bash
# normal operation — stable values
edgesentinel simulate --scenario normal

# stress — temperature ramps up until alerts fire
edgesentinel simulate --scenario stress --interval 1

# spike — sudden temperature spikes every ~20 seconds
edgesentinel simulate --scenario spike
```

Example terminal output with `stress`:

```
[tick 023]
  CPU Temperature        74.98 °C
  CPU Usage              90.68 %
  Memory Usage           64.50 %
2026-04-04 00:11:38 [WARNING] Rule 'high_temperature' fired | sensor=cpu_temp value=75.92°C | anomaly_score=0.9366 threshold=0.7
```

---

## ML Model

The project ships with a script to train and export an anomaly detection model using `scikit-learn`:

```bash
# install training dependencies
pip install scikit-learn skl2onnx

# train the model on normal operation data
python scripts/train_model.py
```

This generates two files:

```
models/
├── anomaly.onnx    → IsolationForest model
└── scaler.onnx     → MinMaxScaler normalizer
```

The model learns what normal operation looks like (~50°C to 65°C) and returns a high score when readings deviate. With the `stress` scenario, you will see the score climb from `0.1` to `0.93` as temperature scales up.

You can replace this with your own model — any framework that exports to ONNX or TFLite works.

---

## Grafana + Prometheus

### Start the stack with Docker

```bash
cd docker/
docker compose up -d
```

This starts:
- Prometheus at `http://localhost:9090`
- Grafana at `http://localhost:3000` — login: `admin` / `edgesentinel`

### Connect Prometheus as a data source

1. Grafana → **Connections** → **Data sources** → **Add data source**
2. Select **Prometheus**
3. URL: `http://prometheus:9090`
4. Click **Save & test**

### Import the dashboard

1. Grafana → **Dashboards** → **Import**
2. Upload `dashboards/edgesentinel.json`
3. Select the Prometheus source → **Import**

### What the dashboard shows

| Panel | What it displays |
|---|---|
| Sensor temperatures | Real-time values per sensor over time |
| Anomaly score | ML model output — 0.0 = normal, 1.0 = anomaly |
| Anomalies detected | Anomaly rate over the last 5 minutes |
| Inference latency P95 | 95% of inferences complete in under X ms |
| Pipeline latency P95 | Total sense → infer → act cycle time |

---

## Exposed metrics

All available at `http://localhost:8000/metrics`:

| Metric | Type | Description |
|---|---|---|
| `edgesentinel_sensor_value` | Gauge | Current sensor reading |
| `edgesentinel_anomaly_score` | Gauge | ML model output (0.0 – 1.0) |
| `edgesentinel_anomaly_total` | Counter | Total anomalies detected |
| `edgesentinel_rule_triggered_total` | Counter | Total rule triggers |
| `edgesentinel_inference_latency_seconds` | Histogram | Per-inference duration |
| `edgesentinel_pipeline_latency_seconds` | Histogram | Full cycle duration |

---

## Available actions

| Type | What it does |
|---|---|
| `log` | Structured log with configurable level |
| `webhook` | HTTP POST JSON to any URL (Slack, Discord, PagerDuty, n8n) |
| `gpio_write` | Write to a GPIO pin (LED, relay, buzzer) with optional duration |

### Webhook payload

```json
{
  "rule": "high_temperature",
  "sensor_id": "cpu_temp",
  "sensor_name": "CPU Temperature",
  "value": 76.22,
  "unit": "°C",
  "timestamp": 1712188800.123,
  "anomaly": {
    "score": 0.9366,
    "threshold": 0.7,
    "model_id": "onnx"
  }
}
```

To test webhooks without a server, use `https://webhook.site` — it generates a free URL that shows incoming payloads in real time in the browser.

---

## Supported sensors

| Config type | Linux source | Notes |
|---|---|---|
| `cpu_temperature` | `/sys/class/thermal` or `vcgencmd` | Auto-detects Raspberry Pi |
| `cpu_usage` | `/proc/stat` | Calculated from tick diff between reads |
| `memory_usage` | `/proc/meminfo` | Uses `MemAvailable` — more accurate than `MemFree` |

To add a new sensor, implement `SensorPort` from `core/ports.py` and register it in `adapters/sensors/registry.py`.

---

## Tests

```bash
pip install pytest pytest-mock pytest-cov

# run all tests
pytest tests/ -v

# with coverage report
pytest tests/ --cov=. --cov-report=term-missing
```

**69 tests, zero failures.** Includes unit, integration and simulation scenario tests — all run without hardware.

| Layer | Coverage |
|---|---|
| `core/` (domain) | 100% |
| `application/engine` | 100% |
| `application/pipeline` | 100% |
| `adapters/inference/dummy` | 100% |
| `adapters/inference/onnx` | 88% |
| `adapters/sensors/simulated` | 100% |
| `config/loader` | 95% |

---

## Project structure

```
edgesentinel/
├── core/                    # pure domain — zero external dependencies
│   ├── ports.py             # abstract contracts
│   ├── entities.py          # immutable dataclasses
│   └── rules.py             # Rule and Condition with cooldown
├── config/
│   ├── schema.py            # YAML structure as dataclasses
│   ├── loader.py            # reads and validates config.yaml
│   └── mapper.py            # converts config into domain objects
├── adapters/
│   ├── sensors/             # cpu_temperature, cpu_usage, memory_usage, simulated
│   ├── inference/           # dummy, onnx, tflite
│   ├── actions/             # log, webhook, gpio_write
│   └── exporter/            # Prometheus HTTP /metrics
├── application/
│   ├── engine.py            # RuleEngine
│   ├── pipeline.py          # sense → infer → act
│   └── monitor.py           # async loop with graceful shutdown
├── cli/
│   ├── main.py              # run / simulate / doctor
│   ├── builder.py           # assembles system from config
│   ├── simulate.py          # simulated sensors
│   └── doctor.py            # environment diagnostics
├── scripts/
│   └── train_model.py       # trains and exports ONNX model
├── docker/
│   ├── docker-compose.yml   # Prometheus + Grafana
│   └── prometheus.yml       # scrape configuration
├── dashboards/
│   └── edgesentinel.json    # ready-to-import Grafana dashboard
└── tests/
    ├── core/
    ├── config/
    ├── adapters/
    ├── application/
    └── integration/
```

---

## Roadmap

- [ ] Redis for distributed state in multi-device deployments
- [ ] Camera frame ingestion with YOLO anomaly detection
- [ ] Additional sensors: GPIO input, I2C, SPI, BME280
- [ ] Terraform configuration for cloud-assisted deployments

---

## License

MIT