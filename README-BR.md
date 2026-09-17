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
- **ONNX** para modelos de anomalia que seguem o contrato do edgesentinel — valor bruto do sensor na entrada, `anomaly_score` na saída (veja [Modelo de anomalia ONNX](#modelo-de-anomalia-onnx))
- **Plug-and-play** — novo modelo é uma linha no `models.yaml`, sem código

### Rule Engine

Avalia regras a cada leitura de sensor com operadores configuráveis:

| Operador | Quando dispara |
|---|---|
| `>` `<` `>=` `<=` `==` | comparação numérica simples |
| `anomaly` | score do modelo ML acima do threshold |

Cada regra tem uma **severidade** — `info`, `warning` (padrão) ou `critical`. Ela define o nível do log e chega a todas as ações da regra, então o mesmo sensor pode ter um aviso aos 75 °C e um alerta crítico aos 85 °C. Severidade inválida no YAML falha na hora de carregar o config, não no primeiro disparo.

### Histórico de eventos

Toda regra que dispara vira uma linha num SQLite local (`data/events.db`): regra, sensor, valor, severidade, horário da leitura e score de anomalia. Sem servidor e sem dependência nova — só a biblioteca padrão.

A gravação nunca atrasa o monitoramento. A leitura do sensor só enfileira o evento, e uma thread dedicada grava em lote; se o disco travar e a fila encher, o evento é descartado com aviso, porque perder uma linha do histórico é melhor que atrasar o próximo alerta. No encerramento, inclusive por Ctrl+C, o que está na fila é gravado antes de sair. Eventos mais velhos que a retenção configurada são removidos ao iniciar.

O histórico é consultado pelo terminal com `edgesentinel events` — veja [Consulta o histórico de eventos](#consulta-o-histórico-de-eventos).

### Observabilidade com OpenTelemetry

O edgesentinel e o AI Service exportam métricas via OTel para o mesmo Collector. O Prometheus coleta e o Grafana plota tudo em tempo real — dois serviços, um dashboard.

### Ações configuráveis

- **`log`** — log estruturado no nível da severidade da regra (`info` → INFO, `warning` → WARNING, `critical` → CRITICAL)
- **`webhook`** — HTTP POST com payload JSON completo
- **`gpio_write`** — aciona pino GPIO (LED, relé, buzzer)

As ações de uma regra podem ser definidas na própria regra ou uma vez por severidade:

```yaml
default_actions:            # para regras que não declaram `actions`
  warning:  [log, webhook]
  critical: [log, webhook, buzzer]
```

A lista `actions` da própria regra substitui o padrão em vez de somar a ele, e `actions: []` não dispara nada, mas o evento continua registrado no histórico. Severidade desconhecida e lista malformada falham no carregamento do config.

---

## Arquitetura

O edgesentinel usa **Arquitetura Hexagonal (Ports & Adapters)**. O domínio central não conhece Prometheus, GPIO nem YOLO — só contratos abstratos.

```
┌─────────────────────────────────────────────────┐
│                    core/                         │
│  ports.py     → contratos abstratos              │
│  entities.py  → dataclasses imutáveis            │
│  rules.py     → Rule, Condition, Severity        │
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
│  store/       → histórico de eventos (SQLite)    │
└─────────────────────────────────────────────────┘
```

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
pip install edgesentinel[otel]      # + OpenTelemetry
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
      name: "Camera Entrada"
      fps_limit: 1.0
      simulated: false

  inference:
    enabled: true
    backend: onnx
    model_path: models/anomaly.onnx

  # modo simples: Prometheus coleta direto em :8000/metrics
  exporter:
    port: 8000
    use_otel: false

  # modo avançado: manda pro OTel Collector, exporta para qualquer backend
  # exporter:
  #   use_otel: true
  #   backend: otlp
  #   endpoint: "http://localhost:4317"
  #   service_name: "edgesentinel"

  # histórico local — habilitado por padrão, mesmo sem este bloco
  event_store:
    enabled: true
    path: data/events.db
    retention_days: 30          # precisa ser > 0

  # ações por severidade, para regras que não declaram `actions`
  default_actions:
    warning:  [log, webhook]
    critical: [log, webhook, buzzer]

  # severity: info | warning | critical  (padrão: warning)
  rules:
    - name: alta_temperatura          # → log, webhook
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 75.0
      severity: warning
      cooldown_seconds: 60

    - name: temperatura_critica       # → log, webhook, buzzer
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 85.0
      severity: critical
      cooldown_seconds: 30

    - name: pessoa_detectada          # → só log: a lista própria vence
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
      url: "https://hooks.exemplo.com/alerta"
    - id: buzzer
      type: gpio_write              # pino GPIO 17
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

### Consulta o histórico de eventos

```bash
edgesentinel events                                   # os 20 mais recentes
edgesentinel events --severity critical --last 24h    # críticos das últimas 24 horas
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

| Opção | Efeito |
|---|---|
| `-s, --severity info\|warning\|critical` | só esse nível |
| `--sensor ID` | só esse sensor |
| `-r, --rule NOME` | só essa regra |
| `--last 30m\|24h\|7d` | janela até agora (`s`, `m`, `h`, `d`) |
| `-n, --limit N` | no máximo N eventos, mais recentes primeiro (padrão 20) |
| `--json` | um objeto JSON por linha, com o campo `time` em ISO |
| `-c, --config CAMINHO` | config de onde vem o `event_store.path` |

O comando só lê: nunca poda eventos antigos e nunca cria o banco. Dados vão para o stdout e mensagens de status para o stderr, então `--json` pode ir direto para um pipe. Código de saída 0 cobre resultados, nenhum resultado e histórico ainda vazio; 1 indica config inválido, store desabilitado ou arquivo ilegível; 2 é opção inválida.

### Diagnostica o ambiente

```bash
edgesentinel doctor
```

---

## Configurando o Grafana do zero

### 1. Abre o Grafana

Acessa `http://localhost:3000` — login `admin` / `edgesentinel`.

### 2. Adiciona o Prometheus como datasource

1. Menu lateral → **Connections** → **Data sources** → **Add data source**
2. Seleciona **Prometheus**
3. URL: `http://prometheus:9090`
4. Clica **Save & test** — deve aparecer "Successfully queried the Prometheus API"

### 3. Importa o dashboard

1. Menu lateral → **Dashboards** → **Import**
2. Clica **Upload dashboard JSON file**
3. Seleciona `dashboards/edgesentinel_dashboard_v2.json`
4. Em **Prometheus**, seleciona o datasource criado no passo anterior
5. Clica **Import**

### 4. Verifica os dados

Deixa o edgesentinel rodando e clica **Refresh** no dashboard. Os painéis mostram dados em até 10 segundos.

> **Dica**: após qualquer customização, exporte o dashboard em **Export → Save to file** e commita no repositório — assim nunca perde ao recriar os containers.

---

## Modo simulação

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

[tick 051]
  CPU Temperature   86.12 °C
  CPU Usage         97.40 %
  Memory Usage      63.10 %

[CRITICAL] Regra 'temperatura_critica' disparada | sensor=cpu_temp value=86.12°C | anomaly_score=0.9366
```

No cenário `stress`, a temperatura passa de 85 °C perto dos 50 segundos e a regra `critical` do config de exemplo dispara. A `alta_temperatura` não se repete ali porque ainda está no cooldown de 60 s.

A simulação grava o histórico como o modo `run`; o caminho do banco aparece no início da saída, na linha `Eventos :`.

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

`weights/` dentro do container é a pasta `models/` do repositório, montada pelo Docker Compose. Arquivo de peso novo vai em `models/`.

---

## Modelo de anomalia ONNX

```bash
pip install scikit-learn skl2onnx
python scripts/train_model.py            # --seed N para outro conjunto de treino
# gera: models/anomaly.onnx
```

O modelo é um arquivo único e autossuficiente, com contrato fixo: entra o valor bruto do sensor, sai um `anomaly_score` em [0, 1]. A normalização e a regra de score moram dentro dele, então o agente e o AI Inference Service só leem essa saída e não têm como discordar.

| Leitura | Score |
|---|---|
| dentro da faixa de treino (~51–65 °C) | IsolationForest, reescalado para 0 – 0.8 |
| fora da faixa de treino | de 0.8 em direção a 1, crescendo com a distância até a faixa |

As duas partes existem porque o IsolationForest sozinho não distingue 75 °C de 95 °C: as árvores só fazem cortes dentro da faixa em que foram treinadas, então todo valor além da borda cai na mesma folha e recebe o mesmo score. Com a regra acima, o modelo de referência dá 0.91 a 75 °C, 0.96 a 85 °C e 0.98 a 95 °C, enquanto 58 °C fica em 0.12. Modelos exportados por versões anteriores do script não têm a saída `anomaly_score` e são recusados no carregamento; treine de novo.

Os arquivos de modelo não são versionados — um clone novo não tem nenhum. O [`models/README.md`](models/README.md) lista cada arquivo, como obtê-lo e quem o usa (em inglês).

---

## Métricas expostas

### edgesentinel

| Métrica Prometheus | Tipo | Descrição |
|---|---|---|
| `edgesentinel_sensor_value` | Gauge | Valor atual do sensor |
| `edgesentinel_anomaly_score` | Gauge | Score do modelo (0.0 – 1.0) |
| `edgesentinel_anomaly_total` | Counter | Total de anomalias |
| `edgesentinel_pipeline_latency_seconds` | Histogram | Tempo do ciclo por sensor |
| `edgesentinel_inference_latency_seconds` | Histogram | Tempo de inferência ML |

### AI Inference Service

| Métrica Prometheus | Tipo | Descrição |
|---|---|---|
| `ai_service_inference_total` | Counter | Total de inferências |
| `ai_service_inference_latency_ms_milliseconds` | Histogram | Latência por inferência |
| `ai_service_detections_total` | Counter | Total de detecções |

> Os nomes acima são os que aparecem no Prometheus e no Grafana. Use-os exatamente assim nas queries PromQL.

---

## Testes

```bash
pip install pytest pytest-mock pytest-cov
pytest tests/ -v
pytest tests/ --cov=. --cov-report=term-missing
```

**249 testes, zero falhas.**

| Camada | Cobertura |
|---|---|
| `core/` | 100% |
| `application/engine` | 100% |
| `application/pipeline` | 100% |
| `adapters/actions/log` | 100% |
| `adapters/inference/dummy` | 100% |
| `config/mapper` | 100% |
| `cli/events` | 99% |
| `config/loader` | 95% |
| `adapters/store/sqlite` | 92% |

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
│   ├── exporter/               # Prometheus legacy + OpenTelemetry
│   └── store/                  # Event Store em SQLite
├── application/                # RuleEngine, Pipeline, MonitorLoop
├── cli/                        # run / simulate / doctor / events
├── ai-inference-service/       # FastAPI com YOLO/ONNX containerizado
├── scripts/                    # train_model.py
├── infra/docker/               # docker-compose, MediaMTX, OTel, Prometheus, Grafana
├── dashboards/                 # edgesentinel_dashboard_v2.json para Grafana
├── data/                       # events.db — gerado em execução, fora do git
└── tests/                      # unitários + integração (249 testes)
```

---

## Decisões de design

**Arquitetura Hexagonal** — o core não conhece infraestrutura. Trocar Prometheus por Datadog é um novo adapter. Trocar ONNX por TFLite é uma linha no config.

**Leitura direta do `/proc`** — sem `psutil`. Mais leve, mais explícito, sem dependência C compilada.

**Descoberta de hardware preguiçosa** — nenhum sensor toca o hardware no construtor. A ausência do dispositivo é informada por `is_available()`, nunca por exceção. O mesmo `config.yaml` sobe num Raspberry Pi e num notebook: sensores indisponíveis são ignorados com aviso, e o resto do monitoramento segue.

**`frozen=True` nas entidades** — o loop é async. Imutabilidade elimina bugs de concorrência.

**`time.monotonic()` para cooldowns** — o relógio de parede pode andar para trás em NTP. O monotônico só avança.

**AI Service separado** — isolamento de falha. Se o YOLO travar, o monitoramento de sensores continua.

**Regra de score dentro do arquivo do modelo** — o agente e o AI Service são construídos e implantados separadamente e não compartilham código. Com a normalização e o score dentro do grafo ONNX, os dois só precisam ler `anomaly_score`: existe um único lugar onde o score é definido e um único lugar para corrigi-lo.

**Histórico com fila e thread de escrita** — os pipelines rodam num pool de threads limitado, e num cartão SD um `fsync` pode travar por centenas de milissegundos. Gravar direto seguraria a thread que lê sensores; enfileirar não. Pelo mesmo motivo, falha no histórico é logada e engolida: o alerta sempre sai.

**MediaMTX** — câmeras IP baratas aceitam 1-2 conexões. O hub distribui para N consumidores sem limitar a câmera.

**OpenTelemetry** — instrumenta uma vez, exporta para qualquer backend. Sem acoplamento ao Prometheus.

---

## Roadmap

- [ ] Redis para estado distribuído em deployments multi-dispositivo
- [ ] gRPC no AI Service como alternativa ao HTTP
- [ ] Sensores adicionais: GPIO input, I2C, SPI, BME280
- [ ] Terraform para cloud-assisted deployments

Versão atual: **0.3.0** (`edgesentinel --version`). O que mudou em cada release está no [CHANGELOG.md](CHANGELOG.md), em inglês; o backlog completo, com dependências e status de entrega por feature, está em [docs/roadmap.json](docs/roadmap.json).

---

## Licença

MIT