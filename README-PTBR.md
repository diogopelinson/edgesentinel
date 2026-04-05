# edgesentinel

> Observabilidade inteligente para dispositivos Linux embarcados — lê sensores de hardware, processa streams de câmera com YOLO, detecta anomalias com ML e envia tudo para o Grafana em tempo real.

---

## O que é o edgesentinel?

O edgesentinel é uma **plataforma de monitoramento para dispositivos embarcados** (Raspberry Pi, Orange Pi, SBCs em geral) que resolve um problema comum: as ferramentas de monitoramento de hardware e as ferramentas de ML vivem em mundos separados.

- Ferramentas de hardware (`psutil`, `gpiozero`) leem sensores mas não entendem de ML
- Ferramentas de ML (`tflite`, `onnxruntime`) rodam modelos mas não monitoram hardware

O edgesentinel une os dois em um sistema coeso, observável e extensível.

---

## Por que usar?

**Sem o edgesentinel**, monitorar um Raspberry Pi com câmera exige colar várias ferramentas com scripts bash, lidar com múltiplas dependências e reinventar a roda a cada projeto.

**Com o edgesentinel**, você declara o que quer monitorar em um `config.yaml`:

```yaml
rules:
  - name: servidor_superaquecendo
    condition:
      sensor_id: cpu_temp
      operator: ">"
      threshold: 80.0
    actions: [log, webhook]
    cooldown_seconds: 60
```

Temperatura acima de 80°C → alerta disparado → webhook enviado → dado no Grafana. Sem código, sem scripts.

---

## O que o sistema faz

### Leitura de sensores de hardware

Lê diretamente dos pseudo-filesystems do Linux — sem dependências pesadas:

- **Temperatura da CPU** via `/sys/class/thermal` ou `vcgencmd` (Raspberry Pi)
- **Uso de CPU** calculado pela diferença de ticks do `/proc/stat`
- **Uso de memória** via `MemAvailable` do `/proc/meminfo`

### Streams de câmera com MediaMTX

O **MediaMTX** é um hub de streams RTSP. A câmera se conecta uma vez e o hub distribui para quantos consumidores quiser — edgesentinel, VLC, browser, outros sistemas — sem limitar a câmera.

```
Câmera IP ──▶ MediaMTX ──▶ edgesentinel (YOLO 1fps)
                      ├──▶ VLC (você assistindo ao vivo)
                      └──▶ Smart Incident Management
```

Isso resolve um problema real: câmeras IP baratas aceitam apenas 1-2 conexões simultâneas.

### AI Inference Service containerizado

Um microserviço FastAPI que expõe modelos de ML via HTTP. O edgesentinel envia um frame e recebe as detecções. Qualquer sistema pode usar o mesmo endpoint.

- **YOLO** para detecção de objetos em frames de câmera
- **ONNX** para qualquer modelo exportado (IsolationForest, classificadores, etc.)
- **Plug-and-play** — novo modelo é uma linha no `models.yaml`, sem código

### Rule Engine

Avalia regras a cada leitura de sensor com operadores configuráveis:

| Operador | Quando dispara |
|---|---|
| `>` `<` `>=` `<=` `==` | comparação numérica simples |
| `anomaly` | score do modelo ML acima do threshold |

### Observabilidade com OpenTelemetry

O edgesentinel e o AI Service exportam métricas via OTel para o mesmo Collector. O Prometheus coleta e o Grafana plota tudo em tempo real — dois serviços, um dashboard.

### Ações configuráveis

- **`log`** — log estruturado com nível configurável
- **`webhook`** — HTTP POST com payload JSON completo
- **`gpio_write`** — aciona pino GPIO (LED, relé, buzzer)

---

## Arquitetura

O edgesentinel usa **Arquitetura Hexagonal (Ports & Adapters)**. O domínio central não conhece Prometheus, GPIO nem YOLO — só contratos abstratos.

```
┌─────────────────────────────────────────────────┐
│                    core/                         │
│  ports.py     → contratos abstratos              │
│  entities.py  → dataclasses imutáveis            │
│  rules.py     → Rule, Condition, cooldown        │
└───────────────────────┬─────────────────────────┘
                        │ tudo depende do core
┌───────────────────────▼─────────────────────────┐
│                 application/                     │
│  engine.py    → avalia regras, despacha ações   │
│  pipeline.py  → sense → infer → act por sensor  │
│  monitor.py   → loop async com shutdown gracioso │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│                  adapters/                       │
│  sensors/     → hardware, câmera, simulado       │
│  inference/   → dummy, onnx, tflite, remote      │
│  actions/     → log, webhook, gpio               │
│  exporter/    → Prometheus legacy + OTel         │
└─────────────────────────────────────────────────┘
```

Trocar o backend de ML é uma linha no `config.yaml`. Adicionar um sensor é um arquivo Python. Substituir o Prometheus é um novo adapter — sem tocar no domínio.

---

## Stack completa

```
Câmera RTSP
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

## Instalação

### Requisitos

| Item | Mínimo | Recomendado |
|---|---|---|
| Python | 3.10+ | 3.11+ |
| Sistema | Linux (SBC) | Raspberry Pi 4 2GB+ |
| Docker | 24+ | 28+ |

> **Windows / Mac**: use o modo simulação para desenvolvimento sem hardware.

### Instala o pacote

```bash
pip install edgesentinel            # base
pip install edgesentinel[onnx]      # + modelo ONNX
pip install edgesentinel[camera]    # + câmera e YOLO local
pip install edgesentinel[gpio]      # + GPIO (Raspberry Pi)
pip install edgesentinel[all]       # tudo
```

### Verifica o ambiente

```bash
edgesentinel doctor
```

---

## Configuração

```yaml
edgesentinel:
  poll_interval_seconds: 5

  # sensores de hardware
  sensors:
    - id: cpu_temp
      type: cpu_temperature
    - id: cpu_usage
      type: cpu_usage
    - id: memory_usage
      type: memory_usage

  # câmeras (MediaMTX como fonte)
  cameras:
    - sensor_id: camera_01
      source: "rtsp://localhost:8554/camera_01"
      name: "Camera Entrada"
      fps_limit: 1.0
      simulated: false

  # inferência via AI Service
  inference:
    enabled: true
    backend: remote
    service_url: "http://localhost:8080"
    model_id: "yolo_v8n"
    threshold: 0.5

  # exportador OpenTelemetry
  exporter:
    use_otel: true
    backend: otlp
    endpoint: "http://localhost:4317"
    service_name: "edgesentinel"

  # regras de alerta
  rules:
    - name: alta_temperatura
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 75.0
      actions: [log, webhook]
      cooldown_seconds: 60

    - name: pessoa_detectada
      condition:
        sensor_id: camera_01
        operator: anomaly
      actions: [log, webhook]
      cooldown_seconds: 30

  # ações disponíveis
  actions:
    - id: log
      type: log
    - id: webhook
      type: webhook
      url: "https://hooks.exemplo.com/alerta"
```

---

## Executando

### Sobe a infraestrutura

```bash
cd infra/docker
docker compose up -d
docker compose ps
```

| Serviço | Porta | Função |
|---|---|---|
| MediaMTX | 8554 / 8888 | Hub de streams de câmera |
| AI Inference Service | 8080 | YOLO e ONNX via HTTP |
| OTel Collector | 4317 | Coleta métricas de todos |
| Prometheus | 9090 | Armazena séries temporais |
| Grafana | 3000 | Dashboard em tempo real |

### Roda o edgesentinel

```bash
# hardware real
edgesentinel run --config config.yaml

# simulação (Windows / Mac)
edgesentinel simulate --scenario stress --interval 1
edgesentinel simulate --scenario normal
edgesentinel simulate --scenario spike
```

### Diagnostica o ambiente

```bash
edgesentinel doctor
```

### Importa o dashboard no Grafana

1. Abre `http://localhost:3000` → `admin` / `edgesentinel`
2. **Dashboards → Import → Upload**
3. Seleciona `dashboards/edgesentinel.json`

---

## Modo simulação

Roda o **pipeline completo** com dados sintéticos — ideal para desenvolvimento sem hardware.

| Cenário | O que acontece |
|---|---|
| `normal` | Valores estáveis, nenhuma regra dispara |
| `stress` | Temperatura sobe progressivamente até disparar alertas |
| `spike` | Picos repentinos a cada ~20 segundos |

```
[tick 023]
  CPU Temperature   74.98 °C
  CPU Usage         90.68 %
  Memory Usage      64.50 %

[WARNING] Regra 'alta_temperatura' disparada | sensor=cpu_temp value=75.92°C | anomaly_score=0.9366
```

---

## AI Inference Service

### Verificando

```bash
curl http://localhost:8080/health
# {"status":"ok","models":1}

curl http://localhost:8080/models
# [{"id":"yolo_v8n","type":"yolo","status":"loaded"}]
```

### Adicionando modelos

Edita `ai-inference-service/models.yaml` e reinicia:

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

Zero código alterado.

---

## Modelo de anomalia ONNX

```bash
pip install scikit-learn skl2onnx
python scripts/train_model.py
# gera: models/anomaly.onnx + models/scaler.onnx
```

O modelo aprende o que é operação normal e detecta quando algo foge do padrão. Com o cenário `stress`, o score chega a `0.93+` quando a temperatura escala.

---

## Métricas expostas

### edgesentinel

| Métrica | Tipo | Descrição |
|---|---|---|
| `edgesentinel.sensor.value` | Gauge | Valor atual do sensor |
| `edgesentinel.anomaly.score` | Gauge | Score do modelo (0.0 – 1.0) |
| `edgesentinel.anomaly.total` | Counter | Total de anomalias |
| `edgesentinel.pipeline.latency` | Histogram | Tempo do ciclo por sensor |

### AI Inference Service

| Métrica | Tipo | Descrição |
|---|---|---|
| `ai_service.inference.total` | Counter | Total de inferências |
| `ai_service.inference.latency_ms` | Histogram | Latência por inferência |
| `ai_service.detections.total` | Counter | Total de detecções |

---

## Testes

```bash
pip install pytest pytest-mock pytest-cov
pytest tests/ -v
pytest tests/ --cov=. --cov-report=term-missing
```

**69 testes, zero falhas.**

| Camada | Cobertura |
|---|---|
| `core/` | 100% |
| `application/engine` | 100% |
| `application/pipeline` | 100% |
| `adapters/inference/dummy` | 100% |
| `config/loader` | 95% |

---

## Estrutura do projeto

```
edgesentinel/
├── core/                       # domínio puro — zero dependências externas
├── config/                     # loader e schema do YAML
├── adapters/
│   ├── sensors/                # cpu_temp, cpu_usage, memory, camera, simulated
│   ├── inference/              # dummy, onnx, tflite, remote (AI Service)
│   ├── actions/                # log, webhook, gpio
│   └── exporter/               # Prometheus legacy + OpenTelemetry
├── application/                # RuleEngine, Pipeline, MonitorLoop
├── cli/                        # run / simulate / doctor
├── ai-inference-service/       # FastAPI com YOLO/ONNX containerizado
├── scripts/                    # train_model.py
├── infra/docker/               # docker-compose, MediaMTX, OTel, Prometheus, Grafana
├── dashboards/                 # dashboard.json para Grafana
└── tests/                      # unitários + integração (69 testes)
```

---

## Decisões de design

**Arquitetura Hexagonal** — o core não conhece infraestrutura. Trocar Prometheus por Datadog é um novo adapter. Trocar ONNX por TFLite é uma linha no config.

**Leitura direta do `/proc`** — sem `psutil`. Mais leve, mais explícito, sem dependência C compilada.

**`frozen=True` nas entidades** — o loop é async. Imutabilidade elimina bugs de concorrência.

**`time.monotonic()` para cooldowns** — o relógio de parede pode andar para trás em NTP. O monotônico só avança.

**AI Service separado** — isolamento de falha. Se o YOLO travar, o monitoramento de sensores continua. Outros sistemas usam o mesmo endpoint.

**MediaMTX** — câmeras IP baratas aceitam 1-2 conexões. O hub distribui para N consumidores sem limitar a câmera.

**OpenTelemetry** — instrumenta uma vez, exporta para qualquer backend. Sem acoplamento ao Prometheus.

---

## Roadmap

- [ ] Redis para estado distribuído em deployments multi-dispositivo
- [ ] gRPC no AI Service como alternativa ao HTTP
- [ ] Sensores adicionais: GPIO input, I2C, SPI, BME280
- [ ] Terraform para cloud-assisted deployments

---

## Licença

MIT