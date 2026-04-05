# Guia de uso — edgesentinel

Esse guia cobre como usar o edgesentinel como biblioteca, como conectar câmeras reais via MediaMTX e como o AI Inference Service funciona na prática.

---

## Índice

1. [Uso via CLI](#1-uso-via-cli)
2. [Uso como biblioteca Python](#2-uso-como-biblioteca-python)
3. [Conectando câmeras reais com MediaMTX](#3-conectando-câmeras-reais-com-mediamtx)
4. [AI Inference Service na prática](#4-ai-inference-service-na-prática)
5. [Criando seu próprio sensor](#5-criando-seu-próprio-sensor)
6. [Criando sua própria ação](#6-criando-sua-própria-ação)
7. [Referência das interfaces](#7-referência-das-interfaces)

---

## 1. Uso via CLI

### Verificar o ambiente

```bash
edgesentinel doctor
```

Mostra o que está disponível no seu sistema — Python, dependências, sensores, modelos, câmeras e a porta do exporter.

### Rodar com hardware real

```bash
edgesentinel run --config config.yaml
edgesentinel run --config config.yaml --log-level DEBUG
```

### Simular sem hardware (Windows / Mac)

O modo `simulate` roda o pipeline completo com dados sintéticos. Você vê as regras disparando, os alertas aparecendo e as métricas chegando no Grafana — sem precisar de Raspberry Pi.

```bash
# operação normal — valores estáveis
edgesentinel simulate --scenario normal

# stress — temperatura sobe até disparar alertas
edgesentinel simulate --scenario stress --interval 1

# spike — picos repentinos a cada ~20 segundos
edgesentinel simulate --scenario spike
```

---

## 2. Uso como biblioteca Python

### Caso mais simples — carrega do config.yaml

```python
from config.loader import load
from cli.builder import build_monitor

config  = load("config.yaml")
monitor = build_monitor(config)
monitor.start()   # bloqueante — Ctrl+C encerra limpo
```

### Controle total — montando manualmente

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


# sensores
sensors = [
    CpuTemperatureSensor(sensor_id="cpu_temp"),       # real (Linux)
    SimulatedSensor("cpu_usage", "CPU", "%",           # simulado (qualquer OS)
                    base_value=60.0, scenario="stress"),
]

# inferência — chama o AI Service via HTTP
inference = RemoteInferenceAdapter(
    model_id="yolo_v8n",
    service_url="http://localhost:8080",
    threshold=0.5,
)
inference.load("")

# ações
actions = {
    "log":     LogAction(action_id="log"),
    "webhook": WebhookAction(action_id="webhook",
                             url="https://hooks.exemplo.com/alerta"),
}

# regras
rules = [
    Rule(
        name="alta_temperatura",
        condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
        action_ids=["log", "webhook"],
        cooldown_seconds=60.0,
    ),
]

# monta e inicia
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

## 3. Conectando câmeras reais com MediaMTX

### Por que o MediaMTX existe

Câmeras IP baratas — especialmente as usadas em IoT industrial — aceitam **1 ou 2 conexões RTSP simultâneas**. Sem o MediaMTX, se o edgesentinel está conectado, você não consegue abrir no VLC. Se você adicionar o Smart Incident Management, a câmera rejeita a conexão.

**Com o MediaMTX:**

```
Câmera                                   Consumidores
   │                                        │
   └──▶ MediaMTX ────────────────────────┬──▶ edgesentinel (YOLO)
                                         ├──▶ VLC / browser
                                         ├──▶ Smart Incident Management
                                         └──▶ gravação em disco
```

A câmera faz **uma conexão** pro MediaMTX. O MediaMTX distribui para quantos consumidores quiser — sem limitar a câmera.

---

### Passo 1 — Sobe o MediaMTX

```bash
cd infra/docker
docker compose up -d mediamtx
```

Verifica se subiu:

```bash
docker compose ps
# mediamtx   Up   :8554 (RTSP), :8888 (HLS), :8889 (WebRTC)
```

---

### Passo 2 — Câmera publica no MediaMTX

**Opção A — Câmera suporta RTSP push nativo**

Acessa a interface web da câmera e configura o destino de stream como:

```
rtsp://IP_DO_SEU_PC:8554/camera_01
```

O nome `camera_01` é livre — você define. Cada câmera usa um nome diferente.

**Opção B — Relay com FFmpeg (câmera não suporta push)**

```bash
# instala FFmpeg se não tiver
# Ubuntu/Raspberry Pi: sudo apt install ffmpeg
# Windows: https://ffmpeg.org/download.html

# faz o relay da câmera para o MediaMTX
ffmpeg -i rtsp://admin:senha@192.168.1.100:554/stream \
       -c copy \
       -f rtsp rtsp://localhost:8554/camera_01
```

Substitui `admin:senha@192.168.1.100:554/stream` pelo endereço real da sua câmera.

**Opção C — Simular sem câmera física**

```bash
# envia um vídeo de teste para o MediaMTX
ffmpeg -re -i video_teste.mp4 \
       -c copy \
       -f rtsp rtsp://localhost:8554/camera_01
```

---

### Passo 3 — Verifica o stream no MediaMTX

Abre o VLC e acessa:

```
rtsp://localhost:8554/camera_01
```

Se a imagem aparecer, o MediaMTX está recebendo e redistribuindo corretamente.

Também pode acessar via browser (HLS):

```
http://localhost:8888/camera_01/index.m3u8
```

---

### Passo 4 — edgesentinel consome do MediaMTX

No `config.yaml`, aponta a câmera para o MediaMTX (não para a câmera direta):

```yaml
cameras:
  - sensor_id: camera_01
    source: "rtsp://localhost:8554/camera_01"   # ← MediaMTX, não a câmera
    name: "Camera Entrada"
    fps_limit: 1.0     # 1 frame por segundo — suficiente para detecção
    simulated: false
```

**Por que `fps_limit: 1.0`?**

O YOLO num Raspberry Pi leva ~200ms por frame. Se a câmera envia 30fps, o sistema não consegue processar em tempo real e a memória vai enchendo. Com `fps_limit: 1.0`, o sensor captura 1 frame por segundo — suficiente para detectar presença de pessoa e sustentável em hardware embarcado.

---

### Passo 5 — Múltiplas câmeras

Cada câmera é uma entrada no MediaMTX e um sensor no edgesentinel:

```yaml
cameras:
  - sensor_id: camera_entrada
    source: "rtsp://localhost:8554/camera_entrada"
    name: "Entrada Principal"
    fps_limit: 1.0
    simulated: false

  - sensor_id: camera_estoque
    source: "rtsp://localhost:8554/camera_estoque"
    name: "Estoque"
    fps_limit: 0.5    # 1 frame a cada 2 segundos — área de baixo risco
    simulated: false
```

E no FFmpeg, dois processos de relay (um por câmera):

```bash
# câmera 1
ffmpeg -i rtsp://admin:senha@192.168.1.100:554/stream \
       -c copy -f rtsp rtsp://localhost:8554/camera_entrada &

# câmera 2
ffmpeg -i rtsp://admin:senha@192.168.1.101:554/stream \
       -c copy -f rtsp rtsp://localhost:8554/camera_estoque &
```

---

## 4. AI Inference Service na prática

### O que é

Um microserviço Python independente que expõe modelos de ML via HTTP. O edgesentinel chama `POST /predict` com um frame e recebe as detecções de volta.

**Por que não rodar o YOLO direto no edgesentinel?**

- Trocar o modelo exigiria alterar o código do edgesentinel
- Não dá para servir outros sistemas (Smart Incident Management, etc.)
- Se o modelo travar, o edgesentinel todo trava

Com o AI Service, o modelo roda isolado. Qualquer sistema chama via HTTP.

---

### Endpoints disponíveis

**`GET /health`** — verifica se o serviço está de pé:

```bash
curl http://localhost:8080/health
# {"status":"ok","models":2}
```

**`GET /models`** — lista modelos carregados:

```bash
curl http://localhost:8080/models
# [
#   {"id":"yolo_v8n","type":"yolo","status":"loaded"},
#   {"id":"anomaly_onnx","type":"onnx","status":"loaded"}
# ]
```

**`POST /predict`** — roda inferência:

```bash
# com frame em base64
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "yolo_v8n",
    "frame_b64": "BASE64_DO_FRAME"
  }'

# com URL de stream (captura um frame automaticamente)
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "yolo_v8n",
    "stream_url": "rtsp://localhost:8554/camera_01"
  }'

# para modelos de anomalia de sensor
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "anomaly_onnx",
    "sensor_value": 85.0
  }'
```

**Resposta:**

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

### Adicionando um novo modelo

Edita `ai-inference-service/models.yaml`:

```yaml
models:
  - id: yolo_v8n
    type: yolo
    path: weights/yolov8n.pt
    target_classes: [person, car, truck]
    confidence_threshold: 0.5

  # adiciona seu modelo aqui
  - id: fire_detector
    type: yolo
    path: weights/fire.pt
    target_classes: [fire, smoke]
    confidence_threshold: 0.4
    description: "Detector de incêndio"
```

Reinicia o serviço:

```bash
cd infra/docker
docker compose restart ai-inference-service
```

Verifica:

```bash
curl http://localhost:8080/models
# [..., {"id":"fire_detector","type":"yolo","status":"loaded"}]
```

---

### Treinando o modelo de anomalia ONNX

O edgesentinel inclui um script para treinar um modelo de detecção de anomalia a partir de dados de sensor:

```bash
pip install scikit-learn skl2onnx
python scripts/train_model.py
```

Isso gera:
- `models/anomaly.onnx` — modelo IsolationForest
- `models/scaler.onnx` — normalizador

Copia para o serviço:

```bash
cp models/anomaly.onnx ai-inference-service/weights/
cp models/scaler.onnx  ai-inference-service/weights/
```

E adiciona no `models.yaml`:

```yaml
  - id: anomaly_onnx
    type: onnx
    path: weights/anomaly.onnx
    scaler_path: weights/scaler.onnx
    confidence_threshold: 0.6
```

---

### edgesentinel chamando o AI Service

No `config.yaml`:

```yaml
inference:
  enabled: true
  backend: remote
  service_url: "http://localhost:8080"
  model_id: "yolo_v8n"
  threshold: 0.5
```

O edgesentinel não sabe se o modelo é local ou remoto — só chama `InferencePort.predict()`. O `RemoteInferenceAdapter` faz o HTTP internamente.

---

## 5. Criando seu próprio sensor

```python
from core.ports import SensorPort
from core.entities import SensorReading


class SensorTemperaturaMotor(SensorPort):
    """Lê temperatura de um motor via arquivo de dispositivo."""

    def __init__(self, sensor_id: str, device_path: str) -> None:
        self.sensor_id   = sensor_id
        self.device_path = device_path

    def read(self) -> SensorReading:
        # lê o valor — pode ser arquivo, serial, I2C, API, etc.
        with open(self.device_path) as f:
            value = float(f.read().strip()) / 1000.0

        return SensorReading(
            sensor_id=self.sensor_id,
            name="Temperatura Motor",
            value=value,
            unit="°C",
        )

    def is_available(self) -> bool:
        import os
        return os.path.exists(self.device_path)
```

Plugar no sistema:

```python
sensor = SensorTemperaturaMotor(
    sensor_id="motor_temp",
    device_path="/sys/class/thermal/thermal_zone1/temp",
)

pipeline = Pipeline(sensor=sensor, engine=engine, inference=inference)
```

---

## 6. Criando sua própria ação

```python
from core.ports import ActionPort
from core.entities import ActionContext
import requests


class TelegramAction(ActionPort):
    """Envia mensagem no Telegram quando uma regra dispara."""

    def __init__(self, action_id: str, token: str, chat_id: str) -> None:
        self.action_id = action_id
        self._token    = token
        self._chat_id  = chat_id

    def execute(self, context: ActionContext) -> None:
        reading = context.reading
        score   = context.score

        texto = (
            f"🚨 *{context.rule_name}*\n"
            f"Sensor: `{reading.sensor_id}`\n"
            f"Valor: `{reading.value}{reading.unit}`"
        )

        if score and score.is_anomaly:
            texto += f"\nAnomaly score: `{score.score:.2f}`"

        requests.post(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            json={"chat_id": self._chat_id, "text": texto, "parse_mode": "Markdown"},
            timeout=5,
        )
```

---

## 7. Referência das interfaces

### `SensorPort`

```python
class SensorPort(ABC):
    def read(self) -> SensorReading: ...    # lê uma medição
    def is_available(self) -> bool: ...     # verifica se existe no hardware
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
    timestamp: float        # auto-gerado
    metadata: dict          # campos extras — frame da câmera fica aqui
```

### `AnomalyScore`

```python
@dataclass(frozen=True)
class AnomalyScore:
    score: float            # 0.0 = normal, 1.0 = anomalia total
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
    score: AnomalyScore | None   # None se inferência desabilitada
    extras: dict
```

### `Rule` e `Condition`

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

### Operadores disponíveis

| Operador | Descrição | Exemplo |
|---|---|---|
| `>` | maior que | `cpu_temp > 75` |
| `<` | menor que | `cpu_temp < 10` |
| `>=` | maior ou igual | `cpu_usage >= 90` |
| `<=` | menor ou igual | `memory_usage <= 20` |
| `==` | igual | `cpu_temp == 0` (sensor morto) |
| `anomaly` | score do modelo ML acima do threshold | qualquer sensor |