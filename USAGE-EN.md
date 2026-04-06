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
from application.engine import RuleEngine
from application.pipeline import Pipeline
from application.monitor import MonitorLoop
from core.rules import Rule, Condition

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
    ),
]

exporter  = PrometheusExporter(port=8000)
engine    = RuleEngine(rules=rules, actions=actions)
pipelines = [
    Pipeline(sensor=s, engine=engine, inference=inference, exporter=exporter)
    for s in sensors
]

monitor = MonitorLoop(pipelines=pipelines, poll_interval_seconds=5.0, exporter=exporter)
monitor.start()
```

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
3. Select `dashboards/edgesentinel.json`
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

---

## 7. Creating your own action

```python
from core.ports import ActionPort
from core.entities import ActionContext
import requests


class TelegramAction(ActionPort):
    """Sends a Telegram message when a rule fires."""

    def __init__(self, action_id: str, token: str, chat_id: str) -> None:
        self.action_id = action_id
        self._token    = token
        self._chat_id  = chat_id

    def execute(self, context: ActionContext) -> None:
        reading = context.reading
        score   = context.score

        text = (
            f"🚨 *{context.rule_name}*\n"
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
    extras: dict
```

### Available operators

| Operator | Description | Example |
|---|---|---|
| `>` | greater than | `cpu_temp > 75` |
| `<` | less than | `cpu_temp < 10` |
| `>=` | greater or equal | `cpu_usage >= 90` |
| `<=` | less or equal | `memory_usage <= 20` |
| `==` | equal | `cpu_temp == 0` (dead sensor) |
| `anomaly` | ML score above threshold | camera, any sensor |