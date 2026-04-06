# Guia de uso — edgesentinel

Esse guia cobre como usar o edgesentinel como biblioteca, como conectar câmeras reais via MediaMTX, como o AI Inference Service funciona na prática e como configurar o Prometheus e o Grafana do zero.

---

## Índice

1. [Uso via CLI](#1-uso-via-cli)
2. [Uso como biblioteca Python](#2-uso-como-biblioteca-python)
3. [Conectando câmeras reais com MediaMTX](#3-conectando-câmeras-reais-com-mediamtx)
4. [AI Inference Service na prática](#4-ai-inference-service-na-prática)
5. [Configurando Prometheus e Grafana](#5-configurando-prometheus-e-grafana)
6. [Criando seu próprio sensor](#6-criando-seu-próprio-sensor)
7. [Criando sua própria ação](#7-criando-sua-própria-ação)
8. [Referência das interfaces](#8-referência-das-interfaces)

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
edgesentinel simulate --scenario normal
edgesentinel simulate --scenario stress --interval 1
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
                             url="https://hooks.exemplo.com/alerta"),
}

rules = [
    Rule(
        name="alta_temperatura",
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

## 3. Conectando câmeras reais com MediaMTX

### Por que o MediaMTX existe

Câmeras IP baratas aceitam **1-2 conexões RTSP simultâneas**. Sem o MediaMTX, se o edgesentinel está conectado, você não consegue abrir no VLC. Com o MediaMTX:

```
Câmera ──▶ MediaMTX ──▶ edgesentinel (YOLO)
                    ├──▶ VLC / browser
                    ├──▶ Smart Incident Management
                    └──▶ gravação em disco
```

A câmera faz uma conexão. O MediaMTX distribui para quantos consumidores quiser.

### Passo 1 — Sobe o MediaMTX

```bash
cd infra/docker
docker compose up -d mediamtx
docker compose ps
# mediamtx   Up   :8554 (RTSP), :8888 (HLS), :8889 (WebRTC)
```

### Passo 2 — Câmera publica no MediaMTX

**Opção A — Câmera suporta RTSP push nativo**

Na interface web da câmera, configura o destino:
```
rtsp://IP_DO_SEU_PC:8554/camera_01
```

**Opção B — Relay com FFmpeg**

```bash
# Ubuntu/Raspberry Pi: sudo apt install ffmpeg
ffmpeg -i rtsp://admin:senha@192.168.1.100:554/stream \
       -c copy \
       -f rtsp rtsp://localhost:8554/camera_01
```

**Opção C — Simular com vídeo local**

```bash
ffmpeg -re -i video_teste.mp4 \
       -c copy \
       -f rtsp rtsp://localhost:8554/camera_01
```

### Passo 3 — Verifica o stream

Abre no VLC: `rtsp://localhost:8554/camera_01`

Ou via browser (HLS): `http://localhost:8888/camera_01/index.m3u8`

### Passo 4 — edgesentinel consome do MediaMTX

```yaml
cameras:
  - sensor_id: camera_01
    source: "rtsp://localhost:8554/camera_01"   # MediaMTX, não a câmera direta
    name: "Camera Entrada"
    fps_limit: 1.0     # 1fps é suficiente para detecção — não sobrecarrega o hardware
    simulated: false
```

### Passo 5 — Múltiplas câmeras

```yaml
cameras:
  - sensor_id: camera_entrada
    source: "rtsp://localhost:8554/camera_entrada"
    fps_limit: 1.0
    simulated: false

  - sensor_id: camera_estoque
    source: "rtsp://localhost:8554/camera_estoque"
    fps_limit: 0.5    # 1 frame a cada 2 segundos — área de baixo risco
    simulated: false
```

---

## 4. AI Inference Service na prática

### Endpoints

```bash
# status
curl http://localhost:8080/health
# {"status":"ok","models":2}

# modelos carregados
curl http://localhost:8080/models
# [{"id":"yolo_v8n","type":"yolo","status":"loaded"},...]

# inferência com frame em base64
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"model_id":"yolo_v8n","frame_b64":"BASE64_AQUI"}'

# inferência com URL de stream (captura um frame automaticamente)
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"model_id":"yolo_v8n","stream_url":"rtsp://localhost:8554/camera_01"}'

# inferência de anomalia em sensor
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"model_id":"anomaly_onnx","sensor_value":85.0}'
```

**Resposta:**

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

### Adicionando um modelo

Edita `ai-inference-service/models.yaml`:

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

## 5. Configurando Prometheus e Grafana

### Dois modos de coleta de métricas

**Modo simples — Prometheus coleta direto do edgesentinel**

Ideal para começar. No `config.yaml`:

```yaml
exporter:
  port: 8000
  use_otel: false
```

No `infra/docker/prometheus.yml`:

```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: "edgesentinel"
    static_configs:
      - targets:
          - "host.docker.internal:8000"   # Windows/Mac
          # ou "172.17.0.1:8000"          # Linux

  - job_name: "ai-service-via-otel"
    static_configs:
      - targets:
          - "edgesentinel-otel-collector:8889"
```

**Modo avançado — via OTel Collector**

Para exportar para Grafana Cloud, Datadog ou InfluxDB sem mudar código. No `config.yaml`:

```yaml
exporter:
  use_otel: true
  backend: otlp
  endpoint: "http://localhost:4317"
  service_name: "edgesentinel"
```

O OTel Collector recebe na `:4317` e expõe pro Prometheus na `:8889`. O `prometheus.yml` aponta só para o Collector:

```yaml
scrape_configs:
  - job_name: "edgesentinel"
    static_configs:
      - targets:
          - "edgesentinel-otel-collector:8889"
```

### Verificando o Prometheus

Abre `http://localhost:9090/targets` — todos os targets devem estar **UP**.

Para confirmar que as métricas estão chegando:

```
http://localhost:9090/api/v1/label/__name__/values
```

Deve retornar os nomes das métricas, incluindo `edgesentinel_sensor_value`.

### Configurando o Grafana do zero

**1. Abre o Grafana**

```
http://localhost:3000
login: admin
senha: edgesentinel
```

**2. Adiciona o Prometheus como datasource**

1. Menu lateral → **Connections** → **Data sources**
2. Clica **Add data source** → seleciona **Prometheus**
3. URL: `http://prometheus:9090`
4. Clica **Save & test**

Se aparecer "Successfully queried the Prometheus API", está funcionando.

**3. Importa o dashboard**

1. Menu lateral → **Dashboards** → **Import**
2. Clica **Upload dashboard JSON file**
3. Seleciona `dashboards/edgesentinel.json`
4. Seleciona o datasource Prometheus criado no passo anterior
5. Clica **Import**

**4. Queries PromQL úteis para criar painéis próprios**

```promql
# valor atual de todos os sensores
edgesentinel_sensor_value

# anomaly score por sensor
edgesentinel_anomaly_score{sensor_id="cpu_temp"}

# taxa de anomalias nos últimos 5 minutos
rate(edgesentinel_anomaly_total[5m])

# latência P95 do pipeline
histogram_quantile(0.95, rate(edgesentinel_pipeline_latency_seconds_bucket[5m]))

# latência P95 do AI Service em ms
histogram_quantile(0.95, rate(ai_service_inference_latency_ms_milliseconds_bucket[5m]))

# taxa de inferências por segundo por modelo
rate(ai_service_inference_total[1m])
```

---

## 6. Criando seu próprio sensor

```python
from core.ports import SensorPort
from core.entities import SensorReading


class SensorTemperaturaMotor(SensorPort):
    """Lê temperatura de um motor via arquivo de dispositivo."""

    def __init__(self, sensor_id: str, device_path: str) -> None:
        self.sensor_id   = sensor_id
        self.device_path = device_path

    def read(self) -> SensorReading:
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

---

## 7. Criando sua própria ação

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

## 8. Referência das interfaces

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
    timestamp: float        # auto-gerado via time.time()
    metadata: dict          # frames de câmera ficam aqui
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
    score: AnomalyScore | None
    extras: dict
```

### Operadores disponíveis

| Operador | Descrição | Exemplo |
|---|---|---|
| `>` | maior que | `cpu_temp > 75` |
| `<` | menor que | `cpu_temp < 10` |
| `>=` | maior ou igual | `cpu_usage >= 90` |
| `<=` | menor ou igual | `memory_usage <= 20` |
| `==` | igual | `cpu_temp == 0` (sensor morto) |
| `anomaly` | score ML acima do threshold | câmera, qualquer sensor |