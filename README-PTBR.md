# Edgesentinel

> Observabilidade inteligente para dispositivos Linux embarcados — lê sensores de hardware, roda inferência de ML no edge e expõe tudo para o Grafana em tempo real.

---

## Visão Geral

A maioria das ferramentas de monitoramento para single-board computers são apenas de hardware (`psutil`, `gpiozero`) ou apenas de ML (`tflite`, `onnxruntime`). O **edgesentinel** une os dois mundos: uma biblioteca Python que coleta dados de sensores, roda modelos leves de detecção de anomalias diretamente no dispositivo e exporta métricas estruturadas para uma stack Prometheus + Grafana — sem configuração complicada.

```
Hardware (Raspberry Pi, SBCs)
        │
        ▼
  edgesentinel (Python)
  ┌──────────────────────────────────────┐
  │  sensores → inferência → rule engine │
  │                │                     │
  │        Prometheus Exporter           │
  └──────────────────────────────────────┘
        │
        ▼
   Prometheus → Grafana
```

---

## Funcionalidades

- **Leitura de sensores de hardware** — temperatura de CPU, uso de CPU e memória via pseudo-filesystems do Linux (`/proc`, `/sys`, `vcgencmd`)
- **Backends de ML plugáveis** — ONNX Runtime, TensorFlow Lite ou um adapter dummy embutido para desenvolvimento
- **Rule engine** — regras declaradas em YAML com operadores configuráveis (`>`, `<`, `==`, `anomaly`) e suporte a cooldown
- **Prometheus exporter** — endpoint HTTP `/metrics` com Gauges por sensor, Counters de anomalia e Histogramas de latência de inferência
- **Dashboard Grafana pronto para importar** — JSON pré-configurado com painéis para valores de sensor, scores de anomalia, disparos de regras e latências P95
- **Ações plugáveis** — log estruturado, webhooks HTTP e escrita em GPIO (LED, relé, buzzer)
- **Shutdown gracioso** — trata `SIGINT` e `SIGTERM` para integração limpa com `systemd`

---

## Arquitetura

O edgesentinel segue **Arquitetura Hexagonal (Ports & Adapters)**. O domínio core não tem dependências externas — sem Prometheus, sem GPIO, sem ONNX. Toda a infraestrutura vive em adapters que implementam interfaces do core.

```
┌─────────────────────────────────────────────┐
│                   core/                      │
│  ports.py       → contratos abstratos        │
│  entities.py    → dataclasses imutáveis      │
│  rules.py       → Rule, Condition, cooldown  │
└────────────────┬────────────────────────────┘
                 │ depende de
┌────────────────▼────────────────────────────┐
│               application/                   │
│  engine.py    → avaliação de regras          │
│  pipeline.py  → sense → infer → act          │
│  monitor.py   → loop async de polling        │
└────────────────┬────────────────────────────┘
                 │ depende de
┌────────────────▼────────────────────────────┐
│                adapters/                     │
│  sensors/     → leitores de hardware         │
│  inference/   → ONNX, TFLite, Dummy          │
│  actions/     → log, webhook, GPIO           │
│  exporter/    → servidor HTTP Prometheus     │
└─────────────────────────────────────────────┘
```

**Regra de dependência:** adapters dependem da application, application depende do core. O core não sabe nada sobre o mundo externo. Trocar um backend (ex: TFLite → ONNX) toca só o adapter — nada mais muda.

---

## Início Rápido

### Requisitos

- Python 3.10+
- Linux (Raspberry Pi, Orange Pi ou qualquer SBC)
- Docker (opcional, para a stack Prometheus + Grafana)

### Instalação

```bash
# instalação base
pip install edgesentinel

# com backend ONNX
pip install edgesentinel[onnx]

# com backend TFLite (recomendado para Raspberry Pi)
pip install edgesentinel[tflite]

# com suporte a GPIO
pip install edgesentinel[gpio]
```

### Configuração

Crie um arquivo `config.yaml`:

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
    model_path: null      # caminho para o arquivo .onnx ou .tflite

  exporter:
    port: 8000

  rules:
    - name: alta_temperatura
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 75.0
      actions: [log]
      cooldown_seconds: 60

    - name: anomalia_detectada
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
      url: "https://hooks.exemplo.com/alerta"
```

### Executar

```bash
edgesentinel --config config.yaml

# com log de debug
edgesentinel --config config.yaml --log-level DEBUG
```

---

## Dashboard Grafana

Importe o dashboard pré-configurado de `dashboards/edgesentinel.json`:

1. Abra o Grafana → **Dashboards** → **Import**
2. Faça upload do `edgesentinel.json`
3. Selecione sua fonte de dados Prometheus

### Painéis incluídos

| Painel | Query |
|---|---|
| Valores dos sensores ao longo do tempo | `edgesentinel_sensor_value` |
| Score de anomalia | `edgesentinel_anomaly_score` |
| Taxa de anomalias (5m) | `rate(edgesentinel_anomaly_total[5m])` |
| Latência de inferência P95 | `histogram_quantile(0.95, ...)` |
| Latência do pipeline P95 | `histogram_quantile(0.95, ...)` |

---

## Referência de Métricas

| Métrica | Tipo | Descrição |
|---|---|---|
| `edgesentinel_sensor_value` | Gauge | Leitura atual do sensor |
| `edgesentinel_anomaly_score` | Gauge | Saída do modelo ML (0.0 – 1.0) |
| `edgesentinel_anomaly_total` | Counter | Total de anomalias detectadas |
| `edgesentinel_rule_triggered_total` | Counter | Total de disparos de regras |
| `edgesentinel_inference_latency_seconds` | Histogram | Duração por inferência |
| `edgesentinel_pipeline_latency_seconds` | Histogram | Duração do ciclo completo |

Todas as métricas incluem labels para `sensor_id`, `sensor_name` e `model_id` — permitindo filtragem por sensor no Grafana.

---

## Sensores Suportados

| Tipo | Fonte | Observações |
|---|---|---|
| `cpu_temperature` | `/sys/class/thermal` ou `vcgencmd` | Detecta Raspberry Pi automaticamente |
| `cpu_usage` | `/proc/stat` | Calculado pela diferença de ticks |
| `memory_usage` | `/proc/meminfo` | Usa `MemAvailable`, não `MemFree` |

Novos sensores implementam `SensorPort` de `core/ports.py` e se registram em `adapters/sensors/registry.py` — um arquivo, uma linha.

---

## Backends de ML

| Backend | Instalação | Caso de uso |
|---|---|---|
| `dummy` | embutido | Desenvolvimento e testes, sem modelo |
| `onnx` | `pip install edgesentinel[onnx]` | Modelos exportados do scikit-learn, PyTorch |
| `tflite` | `pip install edgesentinel[tflite]` | Otimizado para builds ARM do Raspberry Pi |

O contrato do modelo é simples: entrada é um array 1D de float normalizado, saída é um score em `[0.0, 1.0]`. Qualquer framework que exporte para ONNX ou TFLite é compatível.

---

## Rodando os Testes

```bash
pip install pytest pytest-mock pytest-cov
pytest tests/ -v
pytest tests/ --cov=. --cov-report=term-missing
```

### Resumo de cobertura

| Camada | Cobertura |
|---|---|
| `core/` | 100% |
| `config/` | 95%+ |
| `application/engine` | 100% |
| `adapters/inference/dummy` | 100% |
| `adapters/sensors/memory` | 100% |
| `adapters/actions/log` | 100% |

Adapters de infraestrutura (`gpio`, `onnx`, `tflite`, `prometheus`) requerem hardware ARM ou libs não instaláveis em sistemas não-Linux — cobertura zero é esperada em ambiente de desenvolvimento.

---

## Estrutura do Projeto

```
edgesentinel/
├── core/
│   ├── ports.py          # contratos abstratos — SensorPort, InferencePort, ActionPort
│   ├── entities.py       # dataclasses imutáveis — SensorReading, AnomalyScore
│   └── rules.py          # Rule, Condition com suporte a cooldown
├── config/
│   ├── schema.py         # dataclasses espelhando a estrutura do YAML
│   ├── loader.py         # YAML → EdgeSentinelConfig
│   └── mapper.py         # EdgeSentinelConfig → objetos do domínio core
├── adapters/
│   ├── sensors/          # cpu_temperature, cpu_usage, memory_usage
│   ├── inference/        # dummy, onnx, tflite
│   ├── actions/          # log, webhook, gpio_write
│   └── exporter/         # Prometheus HTTP exporter
├── application/
│   ├── engine.py         # RuleEngine — avalia regras e despacha ações
│   ├── pipeline.py       # sense → infer → act por sensor
│   └── monitor.py        # loop async de polling com shutdown gracioso
├── cli/
│   ├── builder.py        # monta todos os componentes a partir do config
│   └── main.py           # entry point da CLI
└── dashboards/
    └── edgesentinel.json # dashboard Grafana pronto para importar
```

---

## Decisões de Design

**Por que Arquitetura Hexagonal?**
Sensores, backends de ML e exporters são todos intercambiáveis sem tocar na lógica de negócio. Adicionar um novo sensor é um arquivo novo implementando `SensorPort`. Trocar ONNX por TFLite é uma linha de config.

**Por que ler `/proc` diretamente em vez de usar `psutil`?**
`psutil` é uma dependência grande. Em um dispositivo com armazenamento limitado, ler `/proc/stat` e `/proc/meminfo` diretamente mantém o footprint mínimo e o código explícito sobre o que lê.

**Por que `frozen=True` nas entidades?**
O loop de monitoramento é assíncrono — objetos `SensorReading` transitam por múltiplas coroutines. Imutabilidade elimina bugs de estado compartilhado por completo.

**Por que `time.monotonic()` para cooldowns e latência?**
O relógio de parede (`time.time()`) pode andar para trás em sincronizações NTP. O relógio monotônico só avança — correto para medir intervalos de tempo.

**Por que um backend de ML dummy?**
O pipeline completo — sensores, regras, Prometheus, Grafana — é demonstrável desde o primeiro dia sem um modelo treinado. O backend de ML entra depois sem mudar nada no restante do sistema.

---

## Licença

MIT