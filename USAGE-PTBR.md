# Guia de uso — edgesentinel

Esse guia cobre como usar o edgesentinel como biblioteca, como conectar câmeras reais via MediaMTX, como o AI Inference Service funciona na prática e como configurar o Prometheus e o Grafana do zero.

> **Este é o guia em português, e continua sendo mantido em arquivo único.** A
> versão em inglês foi dividida em [docs/](docs/README.md) no padrão Diátaxis —
> tutoriais, guias práticos, referência e explicações. O que só existe lá:
> os [tutoriais](docs/tutorials/README.md), a
> [referência de configuração](docs/reference/configuration.md), a
> [referência do banco](docs/reference/database.md) e os
> [registros de decisão](docs/adr/README.md).

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

### Histórico de eventos

Tanto `run` quanto `simulate` gravam cada regra disparada em `data/events.db` (SQLite), com retenção de 30 dias. O caminho e a retenção mudam no bloco `event_store` do `config.yaml`, e `enabled: false` desliga o histórico. Para consultar pelo Python, veja [Consultando o histórico](#consultando-o-histórico).

### Incidentes

A mesma execução também registra incidentes. O primeiro disparo de uma regra abre um, cada disparo seguinte entra nele, e ele fecha quando o sensor volta além da margem de resolução — o threshold menos 10%, ou o `resolve_threshold` quando a regra diz onde fecha. Eventos e incidentes ficam no mesmo banco, e cada evento carrega o `incident_id` do episódio a que pertence.

Três comandos cobrem o ciclo, e funcionam com o agente rodando:

```bash
# o que está aberto agora
edgesentinel incidents

# tudo, inclusive o que já resolveu, do último dia
edgesentinel incidents --all --last 24h

# alguém assumiu: para de repetir as ações, segue registrando
edgesentinel ack 7

# fecha à mão, sem esperar a leitura recuar
edgesentinel resolve 7
```

```
#  ESTADO     SEVERIDADE  REGRA  SENSOR    ABERTO               DURAÇÃO  DISPAROS
1  TRIGGERED  WARNING     hot    cpu_temp  2026-09-23 23:55:32  1s              2

1 incidente(s) aberto(s)
```

A coluna `DISPAROS` mostra quantos disparos aquele incidente agrupou, e `DURAÇÃO` conta desde a abertura enquanto ele está aberto. Reconhecer duas vezes não é erro; reconhecer um incidente já resolvido é recusado, porque o ciclo não volta atrás — o próximo disparo abre outro.

O agente enxerga o reconhecimento na avaliação seguinte — ele lê os incidentes abertos do banco a cada vez, em vez de guardar em memória, que é também o motivo de o ciclo sobreviver a um restart sem etapa de carga. Com `--json`, cada linha é um objeto completo, pronto para `jq`.

### Consultar o histórico

```bash
# o que disparou na última hora
edgesentinel events --last 1h

# só críticos de um sensor
edgesentinel events --severity critical --sensor cpu_temp

# outro config (e portanto outro banco)
edgesentinel events --config /etc/edgesentinel/config.yaml -n 100
```

Com `--json`, cada linha é um objeto completo:

```json
{"event_id": 1162, "time": "2026-09-17T00:35:10-03:00", "timestamp": 1789616110.68, "severity": "warning", "rule_name": "uso_alto_cpu", "sensor_id": "cpu_usage", "value": 92.36, "unit": "%", "anomaly_score": 0.9769}
```

Isso deixa o histórico fácil de usar em script (Linux / macOS):

```bash
# disparos por regra nas últimas 24 horas
edgesentinel events --last 24h --limit 100000 --json | jq -r .rule_name | sort | uniq -c

# alerta externo se houve algum crítico nos últimos 5 minutos
if edgesentinel events --severity critical --last 5m --json | grep -q .; then
    echo "crítico recente"
fi
```

Três garantias sustentam esses usos:

- **stdout só tem dados.** "Nenhum evento encontrado" e erros vão para o stderr, então o `grep -q .` acima só casa com eventos de verdade.
- **Consultar não altera nada.** O comando não aplica a retenção e não cria o banco se ele não existir.
- **O código de saída distingue os casos.** `0` para resultado, nenhum resultado ou histórico ainda vazio; `1` para config inválido, store desabilitado ou arquivo ilegível; `2` para opção inválida, como `--last ontem`.

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
from adapters.store.sqlite import SQLiteEventStore
from application.engine import RuleEngine
from application.pipeline import Pipeline
from application.monitor import MonitorLoop
from core.rules import Rule, Condition, Severity

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
        # sem severity: Severity.WARNING
    ),
    Rule(
        name="temperatura_critica",
        condition=Condition(sensor_id="cpu_temp", operator=">", threshold=85.0),
        action_ids=["log", "webhook"],
        severity=Severity.CRITICAL,
        cooldown_seconds=30.0,
    ),
]

exporter  = PrometheusExporter(port=8000)
events    = SQLiteEventStore(path="data/events.db", retention_days=30)
engine    = RuleEngine(rules=rules, actions=actions, events=events)
pipelines = [
    Pipeline(sensor=s, engine=engine, inference=inference, exporter=exporter)
    for s in sensors
]

monitor = MonitorLoop(
    pipelines=pipelines,
    poll_interval_seconds=5.0,
    exporter=exporter,
    event_store=events,   # o loop abre o store ao iniciar e grava a fila ao encerrar
)
monitor.start()
```

`events` é opcional nos dois lugares: sem ele, nada é gravado e o resto funciona igual. O mesmo objeto precisa ir para o `RuleEngine`, que escreve, e para o `MonitorLoop`, que controla o ciclo de vida.

`default_actions` é um recurso do `config.yaml`, resolvido por `config.mapper.to_rules` antes de as regras chegarem ao engine. Regras montadas à mão, como acima, recebem `action_ids` já resolvido — o `RuleEngine` só enxerga a lista final. Para aproveitar o roteamento por severidade sem YAML, monte um `EdgeSentinelConfig` e passe por `to_rules`:

```python
from config.mapper import to_rules
from config.schema import ConditionConfig, EdgeSentinelConfig, RuleConfig

config = EdgeSentinelConfig(
    sensors=[], actions=[],
    default_actions={"warning": ["log"], "critical": ["log", "webhook"]},
    rules=[
        RuleConfig(
            name="temperatura_critica",
            condition=ConditionConfig(sensor_id="cpu_temp", operator=">", threshold=85.0),
            severity="critical",
        ),
    ],
)
rules = to_rules(config)   # rules[0].action_ids == ["log", "webhook"]
```

### Consultando o histórico

```python
import time
from adapters.store.sqlite import SQLiteEventStore

store = SQLiteEventStore(path="data/events.db")
store.start()
try:
    criticos_24h = store.query(
        severity="critical",
        since=time.time() - 24 * 3600,
        limit=20,
    )
    for e in criticos_24h:
        print(e.event_id, e.rule_name, e.sensor_id, e.value, e.unit, e.anomaly_score)
finally:
    store.close()
```

- Filtros combináveis: `severity`, `sensor_id`, `rule_name`, `since` e `until` (ambos inclusivos, em timestamp Unix) e `limit` (padrão 100).
- O resultado vem do mais recente para o mais antigo.
- `start()` aplica a retenção: eventos mais velhos que `retention_days` são removidos ao abrir.
- `start()` cria o arquivo e as pastas se não existirem.

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

Os caminhos `weights/` apontam para a pasta `models/` do repositório, que o Docker Compose monta em `/app/weights`. Ou seja, `weights/fire.pt` é o arquivo `models/fire.pt` na máquina. Arquivos de peso nunca são commitados: o `.gitignore` exclui `models/*.pt`, `models/*.onnx` e `ai-inference-service/weights/`, e o [`models/README.md`](models/README.md) explica como obter os que o projeto usa.

### Modelos de anomalia ONNX

Modelos `type: onnx`, no AI Service e no agente (`inference.backend: onnx`), seguem um contrato só:

| | Nome | Tipo | Significado |
|---|---|---|---|
| entrada | qualquer | `float32 [N, 1]` | o valor bruto do sensor, sem normalizar |
| saída | `anomaly_score` | `float32 [N, 1]` | 0 = normal, 1 = anomalia máxima |

O `scripts/train_model.py` gera um modelo assim, com a normalização e a regra de score dentro do grafo. Qualquer outro arquivo ONNX com essa entrada e essa saída também funciona. Um arquivo sem a saída `anomaly_score` é recusado no carregamento — o AI Service registra o erro e continua servindo os outros modelos. Um `scaler_path` que tenha ficado no `models.yaml` de versões anteriores é ignorado com um aviso.

Para o `anomaly_onnx`, a resposta do `/predict` traz uma detecção `anomaly` cuja `confidence` é o `anomaly_score`, ou nenhuma detecção quando o score fica abaixo do `confidence_threshold`.

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
3. Seleciona `dashboards/edgesentinel_dashboard_v2.json`
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

### Contrato de disponibilidade

Todo sensor segue três regras, e o exemplo acima já cumpre as três:

1. **O `__init__` não toca o hardware** — só guarda a configuração. Nada de abrir arquivo, procurar dispositivo ou chamar comando no construtor.
2. **A ausência é informada por `is_available()`**, nunca por exceção. No boot, o `edgesentinel run` ignora sensores indisponíveis com um `WARNING` e segue com os demais; o `edgesentinel doctor` os lista como indisponíveis. Um construtor que levanta exceção desvia os dois para o caminho de erro.
3. **Quando `read()` falhar, a mensagem diz onde procurou.** `"Nenhuma fonte encontrada. Caminhos tentados: /sys/..., /usr/bin/..."` transforma o diagnóstico numa consulta.

Herdando de `adapters.sensors.base.BaseSensor` em vez de `SensorPort`, o `is_available()` já vem pronto: ele tenta um `read()` e devolve `False` se a leitura levantar exceção.

---

## 7. Criando sua própria ação

```python
from core.ports import ActionPort
from core.entities import ActionContext
from core.rules import Severity
import requests


ICONES = {
    Severity.INFO:     "ℹ️",
    Severity.WARNING:  "⚠️",
    Severity.CRITICAL: "🚨",
}


class TelegramAction(ActionPort):
    """Envia mensagem no Telegram quando uma regra dispara."""

    def __init__(self, action_id: str, token: str, chat_id: str) -> None:
        self.action_id = action_id
        self._token    = token
        self._chat_id  = chat_id

    def execute(self, context: ActionContext) -> None:
        reading  = context.reading
        score    = context.score
        severity = context.extras.get("severity", Severity.WARNING)

        texto = (
            f"{ICONES[severity]} *{context.rule_name}* [{severity.value}]\n"
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

A severidade da regra que disparou chega em `context.extras["severity"]` como um `Severity`. Para texto, use `.value` — no Python 3.10, `str(Severity.CRITICAL)` devolve `'Severity.CRITICAL'`, não `'critical'`. O `.get` com padrão cobre o caso de a ação ser chamada fora do `RuleEngine`.

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

### `EventPort`

```python
class EventPort(ABC):
    def start(self) -> None: ...                 # construir não toca o disco
    def append(self, event: Event) -> None: ...  # nunca bloqueia quem chama
    def query(self, *, severity=None, sensor_id=None, rule_name=None,
              since=None, until=None, limit=100) -> list[Event]: ...
    def prune(self, before: float) -> int: ...   # devolve quantos removeu
    def close(self) -> None: ...                 # grava o que estiver pendente
```

### `StatePort`

```python
class StatePort(ABC):
    # toma a chave por ttl_seconds; False enquanto uma tomada anterior
    # estiver viva. Tomar e verificar são uma operação atômica, e nenhum
    # timestamp é exposto: o epoch do monotônico não vale em outro processo
    def try_acquire(self, key: str, ttl_seconds: float) -> bool: ...
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
```

O `RuleEngine` usa a porta para o cooldown das regras, na chave `cooldown:<nome da regra>`, e por padrão usa o `adapters.state.memory.InMemoryState` — estado do processo, baseado em `time.monotonic()`. Para passar outro, use `RuleEngine(..., state=meu_state)`; o adapter de Redis que fará o cooldown valer entre dispositivos entra do mesmo jeito. Qualquer implementação precisa passar por `tests/adapters/test_state_contract.py`.

### `IncidentPort`

```python
class IncidentPort(ABC):
    # devolve o incidente com o incident_id atribuído pelo store
    def open_incident(self, incident: Incident) -> Incident: ...
    def acknowledge_incident(self, incident_id: int, at: float) -> None: ...
    def resolve_incident(self, incident_id: int, at: float) -> None: ...
    def open_incidents(self) -> list[Incident]: ...   # mais antigo primeiro
```

O `SQLiteEventStore` implementa esta porta junto com a `EventPort`, então eventos e incidentes caem no mesmo arquivo e um único `close()` descarrega os dois. Diferente do `StatePort`, aqui o estado precisa ser durável e consultável: o operador lista o que está aberto e reconhece de outro processo.

Duas regras que qualquer implementação tem de manter, ambas cobertas por `tests/adapters/test_sqlite_incidents.py`: uma regra tem no máximo um incidente aberto — no SQLite isso é um índice único parcial, `UNIQUE (rule_name) WHERE state != 'resolved'`, então a abertura concorrente é recusada pelo armazenamento e não por um lock no engine — e `open_incidents()` devolve também os reconhecidos, porque reconhecer não fecha nada.

Para passar uma implementação: `RuleEngine(..., incidents=meu_store)`. Sem nenhuma, o engine continua avaliando, alertando e registrando: os eventos vão para o histórico com o `incident_id` vazio. Uma loja que lança exceção recebe o mesmo tratamento, porque o incidente é contexto do alarme e não pode silenciá-lo.

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
    extras: dict            # extras["severity"] traz a Severity da regra
```

### `Event`

```python
@dataclass(frozen=True)
class Event:
    rule_name: str
    sensor_id: str
    value: float
    unit: str
    severity: str                   # texto puro: "info", "warning", "critical"
    timestamp: float                # horário da leitura, não da avaliação
    anomaly_score: float | None     # None em regras sem inferência
    event_id: int | None            # atribuído pelo store ao gravar
    incident_id: int | None         # incidente que agrupa este disparo
```

### `Incident`

```python
@dataclass(frozen=True)
class Incident:
    rule_name: str
    sensor_id: str
    severity: str                       # texto puro, como em Event.severity
    state: IncidentState = IncidentState.TRIGGERED
    opened_at: float = field(default_factory=time.time)
    acknowledged_at: float | None = None
    resolved_at: float | None = None
    incident_id: int | None = None      # atribuído pelo store ao abrir

    @property
    def is_open(self) -> bool: ...              # reconhecido ainda é aberto
    def acknowledge(self, at: float) -> "Incident": ...
    def resolve(self, at: float) -> "Incident": ...
```

Imutável como as outras entidades: as transições devolvem outro incidente em vez de alterar o existente.

### `IncidentState`

```python
class IncidentState(str, Enum):
    TRIGGERED    = "triggered"      # aberto, alertando a cada disparo
    ACKNOWLEDGED = "acknowledged"   # o histórico continua, as ações param
    RESOLVED     = "resolved"       # fechado; o próximo disparo abre outro
```

Não existe estado `normal`. Normal é a ausência de incidente aberto — guardá-lo daria uma linha para cada regra que nunca disparou.

### `Rule`

```python
@dataclass
class Rule:
    name: str
    condition: Condition
    action_ids: list[str]
    severity: Severity = Severity.WARNING
    enabled: bool = True
    cooldown_seconds: float = 0.0
```

### `Severity`

```python
class Severity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"     # padrão
    CRITICAL = "critical"

    @classmethod
    def from_name(cls, name: str) -> "Severity": ...   # ignora maiúsculas
```

| Severidade | Nível no `log` | Uso típico |
|---|---|---|
| `info` | INFO | evento esperado que vale registrar |
| `warning` | WARNING | fora do normal, merece atenção — **padrão** |
| `critical` | CRITICAL | exige ação imediata |

### Resolução de ações (`default_actions`)

| A regra declara | `default_actions` tem a severidade da regra | Ações disparadas |
|---|---|---|
| `actions: [log]` | tanto faz | `[log]` — a lista da regra, sem somar ao padrão |
| `actions: []` | tanto faz | nenhuma — o evento ainda vai para o histórico |
| nada | sim | a lista de `default_actions` para essa severidade |
| nada | não | nenhuma |

Regras sem ação nenhuma aparecem em `DEBUG` no logger `edgesentinel.config`. No `config.yaml`, severidade desconhecida em `default_actions`, a mesma severidade escrita duas vezes (`warning` e `Warning`), lista que não seja de ids e `actions` de regra escrito como mapa falham ao carregar.

### Operadores disponíveis

| Operador | Descrição | Exemplo |
|---|---|---|
| `>` | maior que | `cpu_temp > 75` |
| `<` | menor que | `cpu_temp < 10` |
| `>=` | maior ou igual | `cpu_usage >= 90` |
| `<=` | menor ou igual | `memory_usage <= 20` |
| `==` | igual | `cpu_temp == 0` (sensor morto) |

Uma condição com limite superior ou inferior aceita também `resolve_threshold`, o valor em que o incidente fecha:

```yaml
condition:
  sensor_id: cpu_temp
  operator: ">"
  threshold: 85.0
  resolve_threshold: 80.0     # o padrão seria 76.5
```

Sem ele, o ponto de fechamento é o threshold menos 10% do seu valor absoluto, para o lado oposto ao alarme: `> 80` fecha em 72, `< 10` fecha em 11, e threshold 0 não tem margem. O loader recusa um valor do lado do alarme — `> 85` resolvendo em 90 fecharia o incidente com o sensor ainda acima do limite — e recusa o campo nos dois operadores sem borda numérica: `==` fecha assim que o valor muda, e `anomaly` fecha quando o score volta para baixo do threshold dele. Com a inferência fora do ar não há score, e sem score não há resolução: o incidente fica aberto.

| `anomaly` | score ML acima do threshold | câmera, qualquer sensor |