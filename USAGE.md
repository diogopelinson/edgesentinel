# Usage guide — edgesentinel

This guide covers how to use edgesentinel as a library, how to connect real cameras via MediaMTX, and how the AI Inference Service works in practice.

---

## Table of contents

1. [CLI usage](#1-cli-usage)
2. [Library usage](#2-library-usage)
3. [Connecting real cameras with MediaMTX](#3-connecting-real-cameras-with-mediamtx)
4. [AI Inference Service in practice](#4-ai-inference-service-in-practice)
5. [Creating your own sensor](#5-creating-your-own-sensor)
6. [Creating your own action](#6-creating-your-own-action)
7. [Interface reference](#7-interface-reference)

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

The `simulate` mode runs the full pipeline with synthetic data. You can watch rules firing, alerts appearing and metrics flowing into Grafana — without a Raspberry Pi.

```bash
# normal operation — stable values
edgesentinel simulate --scenario normal

# stress — temperature ramps up until alerts fire
edgesentinel simulate --scenario stress --interval 1

# spike — sudden temperature spikes every ~20 seconds
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
from adapters.exporter.otel import OTelExporter
from application.engine import RuleEngine
from application.pipeline import Pipeline
from application.monitor import MonitorLoop
from core.rules import Rule, Condition


# sensors
sensors = [
    CpuTemperatureSensor(sensor_id="cpu_temp"),         # real (Linux)
    SimulatedSensor("cpu_usage", "CPU", "%",             # simulated (any OS)
                    base_value=60.0, scenario="stress"),
]

# inference — calls the AI Service via HTTP
inference = RemoteInferenceAdapter(
    model_id="yolo_v8n",
    service_url="http://localhost:8080",
    threshold=0.5,
)
inference.load("")

# actions
actions = {
    "log":     LogAction(action_id="log"),
    "webhook": WebhookAction(action_id="webhook",
                             url="https://hooks.example.com/alert"),
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
exporter  = OTelExporter(backend="otlp", endpoint="http://localhost:4317")
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

Cheap IP cameras — especially those used in industrial IoT — accept **only 1-2 simultaneous RTSP connections**. Without MediaMTX, if edgesentinel is connected, you cannot open the stream in VLC at the same time. Adding a second system like Smart Incident Management would be rejected by the camera.

**With MediaMTX:**

```
Camera                                   Consumers
   │                                        │
   └──▶ MediaMTX ────────────────────────┬──▶ edgesentinel (YOLO)
                                         ├──▶ VLC / browser
                                         ├──▶ Smart Incident Management
                                         └──▶ disk recording
```

The camera makes **one connection** to MediaMTX. MediaMTX distributes to as many consumers as needed — without limiting the camera.

---

### Step 1 — Start MediaMTX

```bash
cd infra/docker
docker compose up -d mediamtx
```

Verify it started:

```bash
docker compose ps
# mediamtx   Up   :8554 (RTSP), :8888 (HLS), :8889 (WebRTC)
```

---

### Step 2 — Camera publishes to MediaMTX

**Option A — Camera supports native RTSP push**

Access the camera's web interface and set the stream destination to:

```
rtsp://YOUR_PC_IP:8554/camera_01
```

The name `camera_01` is arbitrary — you define it. Each camera uses a different name.

**Option B — Relay with FFmpeg (camera doesn't support push)**

```bash
# install FFmpeg if you don't have it
# Ubuntu/Raspberry Pi: sudo apt install ffmpeg
# Windows: https://ffmpeg.org/download.html

# relay from camera to MediaMTX
ffmpeg -i rtsp://admin:password@192.168.1.100:554/stream \
       -c copy \
       -f rtsp rtsp://localhost:8554/camera_01
```

Replace `admin:password@192.168.1.100:554/stream` with your actual camera address.

**Option C — Simulate without a physical camera**

```bash
# send a test video to MediaMTX
ffmpeg -re -i test_video.mp4 \
       -c copy \
       -f rtsp rtsp://localhost:8554/camera_01
```

---

### Step 3 — Verify the stream in MediaMTX

Open VLC and access:

```
rtsp://localhost:8554/camera_01
```

If the image appears, MediaMTX is receiving and redistributing correctly.

You can also access via browser (HLS):

```
http://localhost:8888/camera_01/index.m3u8
```

---

### Step 4 — edgesentinel consumes from MediaMTX

In `config.yaml`, point the camera to MediaMTX (not directly to the camera):

```yaml
cameras:
  - sensor_id: camera_01
    source: "rtsp://localhost:8554/camera_01"   # ← MediaMTX, not the camera
    name: "Entrance Camera"
    fps_limit: 1.0     # 1 frame per second — enough for detection
    simulated: false
```

**Why `fps_limit: 1.0`?**

YOLO on a Raspberry Pi takes ~200ms per frame. If the camera sends 30fps, the system cannot process in real time and memory will fill up. With `fps_limit: 1.0`, the sensor captures 1 frame per second — enough to detect a person's presence and sustainable on embedded hardware.

---

### Step 5 — Multiple cameras

Each camera is one entry in MediaMTX and one sensor in edgesentinel:

```yaml
cameras:
  - sensor_id: camera_entrance
    source: "rtsp://localhost:8554/camera_entrance"
    name: "Main Entrance"
    fps_limit: 1.0
    simulated: false

  - sensor_id: camera_storage
    source: "rtsp://localhost:8554/camera_storage"
    name: "Storage Room"
    fps_limit: 0.5    # 1 frame every 2 seconds — low risk area
    simulated: false
```

And in FFmpeg, two relay processes (one per camera):

```bash
# camera 1
ffmpeg -i rtsp://admin:password@192.168.1.100:554/stream \
       -c copy -f rtsp rtsp://localhost:8554/camera_entrance &

# camera 2
ffmpeg -i rtsp://admin:password@192.168.1.101:554/stream \
       -c copy -f rtsp rtsp://localhost:8554/camera_storage &
```

---

## 4. AI Inference Service in practice

### What it is

A standalone Python microservice that exposes ML models via HTTP. edgesentinel calls `POST /predict` with a frame and gets detections back.

**Why not run YOLO directly in edgesentinel?**

- Swapping the model would require changing edgesentinel's code
- Other systems (Smart Incident Management, etc.) cannot use it
- If the model crashes, all of edgesentinel crashes

With the AI Service, the model runs in isolation. Any system calls it via HTTP.

---

### Available endpoints

**`GET /health`** — check if the service is up:

```bash
curl http://localhost:8080/health
# {"status":"ok","models":2}
```

**`GET /models`** — list loaded models:

```bash
curl http://localhost:8080/models
# [
#   {"id":"yolo_v8n","type":"yolo","status":"loaded"},
#   {"id":"anomaly_onnx","type":"onnx","status":"loaded"}
# ]
```

**`POST /predict`** — run inference:

```bash
# with base64 frame
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "yolo_v8n",
    "frame_b64": "BASE64_FRAME_HERE"
  }'

# with stream URL (captures one frame automatically)
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "yolo_v8n",
    "stream_url": "rtsp://localhost:8554/camera_01"
  }'

# for sensor anomaly models
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "anomaly_onnx",
    "sensor_value": 85.0
  }'
```

**Response:**

```json
{
  "model_id": "yolo_v8n",
  "detections": [
    {
      "class_name": "person",
      "confidence": 0.91,
      "bbox": [120.0, 50.0, 380.0, 480.0]
    }
  ],
  "inference_latency_ms": 178.42,
  "timestamp": 1712188800.123,
  "has_detections": true
}
```

---

### Adding a new model

Edit `ai-inference-service/models.yaml`:

```yaml
models:
  - id: yolo_v8n
    type: yolo
    path: weights/yolov8n.pt
    target_classes: [person, car, truck]
    confidence_threshold: 0.5

  # add your model here
  - id: fire_detector
    type: yolo
    path: weights/fire.pt
    target_classes: [fire, smoke]
    confidence_threshold: 0.4
    description: "Fire and smoke detector"
```

Restart the service:

```bash
cd infra/docker
docker compose restart ai-inference-service
```

Verify:

```bash
curl http://localhost:8080/models
# [..., {"id":"fire_detector","type":"yolo","status":"loaded"}]
```

---

### Training the ONNX anomaly model

edgesentinel includes a script to train an anomaly detection model from sensor data:

```bash
pip install scikit-learn skl2onnx
python scripts/train_model.py
```

This generates:
- `models/anomaly.onnx` — IsolationForest model
- `models/scaler.onnx` — MinMaxScaler normalizer

Copy to the service:

```bash
cp models/anomaly.onnx ai-inference-service/weights/
cp models/scaler.onnx  ai-inference-service/weights/
```

And add to `models.yaml`:

```yaml
  - id: anomaly_onnx
    type: onnx
    path: weights/anomaly.onnx
    scaler_path: weights/scaler.onnx
    confidence_threshold: 0.6
```

---

### edgesentinel calling the AI Service

In `config.yaml`:

```yaml
inference:
  enabled: true
  backend: remote
  service_url: "http://localhost:8080"
  model_id: "yolo_v8n"
  threshold: 0.5
```

edgesentinel does not know whether the model is local or remote — it just calls `InferencePort.predict()`. The `RemoteInferenceAdapter` handles the HTTP internally.

---

## 5. Creating your own sensor

```python
from core.ports import SensorPort
from core.entities import SensorReading


class MotorTemperatureSensor(SensorPort):
    """Reads motor temperature from a device file."""

    def __init__(self, sensor_id: str, device_path: str) -> None:
        self.sensor_id   = sensor_id
        self.device_path = device_path

    def read(self) -> SensorReading:
        # read the value — can be a file, serial port, I2C, API, etc.
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

Plug it into the system:

```python
sensor = MotorTemperatureSensor(
    sensor_id="motor_temp",
    device_path="/sys/class/thermal/thermal_zone1/temp",
)

pipeline = Pipeline(sensor=sensor, engine=engine, inference=inference)
```

---

## 6. Creating your own action

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

## 7. Interface reference

### `SensorPort`

```python
class SensorPort(ABC):
    def read(self) -> SensorReading: ...    # reads one measurement
    def is_available(self) -> bool: ...     # checks if sensor exists on hardware
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
    timestamp: float        # auto-generated
    metadata: dict          # extra fields — camera frame lives here
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
    score: AnomalyScore | None   # None if inference is disabled
    extras: dict
```

### `Rule` and `Condition`

```python
@dataclass
class Rule:
    name: str
    condition: Condition
    action_ids: list[str]
    enabled: bool = True
    cooldown_seconds: float = 0.0

@dataclass
class Condition:
    sensor_id: str
    operator: str        # ">" | "<" | ">=" | "<=" | "==" | "anomaly"
    threshold: float = 0.0
```

### Available operators

| Operator | Description | Example |
|---|---|---|
| `>` | greater than | `cpu_temp > 75` |
| `<` | less than | `cpu_temp < 10` |
| `>=` | greater or equal | `cpu_usage >= 90` |
| `<=` | less or equal | `memory_usage <= 20` |
| `==` | equal | `cpu_temp == 0` (dead sensor) |
| `anomaly` | ML model score above threshold | any sensor |