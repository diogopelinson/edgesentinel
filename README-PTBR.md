# edgesentinel

> Observabilidade inteligente para dispositivos Linux embarcados — lê sensores de hardware, detecta anomalias com ML e envia tudo pro Grafana em tempo real.

---

## O que é isso?

A maioria das ferramentas para Raspberry Pi e SBCs são **só de hardware** (`psutil`, `gpiozero`) ou **só de ML** (`tflite`, `onnxruntime`). O `edgesentinel` une os dois:

- Lê temperatura, CPU e memória direto dos pseudo-filesystems do Linux
- Roda um modelo de detecção de anomalia **no próprio dispositivo**
- Exporta métricas pro Prometheus e plota no Grafana em tempo real
- Dispara alertas via log, webhook ou GPIO quando algo foge do normal

Tudo com um único arquivo `config.yaml` e zero boilerplate.

---

## Como funciona na prática

```
Raspberry Pi / SBC
      │
      ▼
edgesentinel lê os sensores a cada N segundos
      │
      ├─ modelo ML avalia se é anomalia (score 0.0 → 1.0)
      │
      ├─ rule engine verifica as regras do config.yaml
      │
      ├─ ações disparam (log, webhook, GPIO)
      │
      └─ /metrics exposto na porta 8000
            │
            ▼
      Prometheus coleta a cada 5s
            │
            ▼
      Grafana plota em tempo real
```

---

## Instalação

### Requisitos

- Python 3.10+
- Linux (Raspberry Pi, Orange Pi ou qualquer SBC)
- Docker (opcional — para Prometheus + Grafana)

### Instala o pacote

```bash
# instalação base
pip install edgesentinel

# com modelo ONNX (scikit-learn, PyTorch)
pip install edgesentinel[onnx]

# com TFLite (mais leve, recomendado pro Raspberry Pi)
pip install edgesentinel[tflite]

# com suporte a GPIO (LED, relé, buzzer)
pip install edgesentinel[gpio]
```

### Verifica se está tudo certo

```bash
edgesentinel doctor
```

Esse comando inspeciona o ambiente e mostra o que está disponível:

```
edgesentinel doctor
====================================================
Python
  OK      Python 3.11.2

Dependências
  OK      pyyaml 6.0.3
  OK      prometheus-client 0.24.1
  OK      numpy 1.26.4
  AVISO   tflite-runtime — não instalado (opcional)

Sensores
  OK      cpu_temperature      62.5 °C
  OK      cpu_usage            34.1 %
  OK      memory_usage         48.3 %

Backends de inferência
  OK      dummy      disponível
  OK      onnx       disponível

Exporter
  OK      porta 8000 livre
====================================================
Tudo certo — sistema pronto para rodar.
```

---

## Configuração

Crie um arquivo `config.yaml` na raiz do projeto:

```yaml
edgesentinel:
  poll_interval_seconds: 5       # intervalo de leitura dos sensores

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
    port: 8000                   # Prometheus vai buscar métricas aqui

  rules:
    - name: alta_temperatura
      condition:
        sensor_id: cpu_temp
        operator: ">"            # operadores disponíveis: > < >= <= == anomaly
        threshold: 75.0
      actions: [log, webhook]
      cooldown_seconds: 60       # não dispara de novo por 60s

    - name: anomalia_detectada
      condition:
        sensor_id: cpu_temp
        operator: anomaly        # usa o score do modelo ML
      actions: [log, webhook]
      cooldown_seconds: 30

  actions:
    - id: log
      type: log
    - id: webhook
      type: webhook
      url: "https://hooks.exemplo.com/alerta"
```

---

## Executando

### No hardware real (Raspberry Pi / SBC)

```bash
edgesentinel run --config config.yaml
```

### Simulando no Windows / Mac (sem hardware)

O modo `simulate` roda o pipeline completo com dados sintéticos. Você vê as regras disparando, os logs aparecendo e as métricas chegando no Grafana — sem precisar de hardware.

```bash
# operação normal — valores estáveis
edgesentinel simulate --scenario normal

# stress — temperatura sobe progressivamente até disparar alertas
edgesentinel simulate --scenario stress --interval 1

# spike — picos repentinos de temperatura a cada ~20 segundos
edgesentinel simulate --scenario spike
```

Exemplo do que aparece no terminal com `stress`:

```
[tick 023]
  CPU Temperature        74.98 °C
  CPU Usage              90.68 %
  Memory Usage           64.50 %
2026-04-04 00:11:38 [WARNING] Regra 'alta_temperatura' disparada | sensor=cpu_temp value=75.92°C | anomaly_score=0.9366 threshold=0.7
```

---

## Modelo ML

O sistema vem com um script para treinar e exportar um modelo de detecção de anomalia com `scikit-learn`:

```bash
# instala dependências de treino
pip install scikit-learn skl2onnx

# treina o modelo com dados de operação normal
python scripts/train_model.py
```

O script gera dois arquivos:

```
models/
├── anomaly.onnx    → modelo IsolationForest
└── scaler.onnx     → normalizador MinMaxScaler
```

O modelo aprende o que é operação normal (~50°C a 65°C) e retorna score alto quando a temperatura foge desse padrão. Com `stress`, você vai ver o score subir de `0.1` até `0.93` conforme a temperatura escala.

Você pode substituir pelo seu próprio modelo — qualquer framework que exporte para ONNX ou TFLite funciona.

---

## Grafana + Prometheus

### Sobe a stack com Docker

```bash
cd docker/
docker compose up -d
```

Isso sobe:
- Prometheus em `http://localhost:9090`
- Grafana em `http://localhost:3000` — login: `admin` / `edgesentinel`

### Conecta ao Prometheus

1. Grafana → **Connections** → **Data sources** → **Add data source**
2. Seleciona **Prometheus**
3. URL: `http://prometheus:9090`
4. Clica **Save & test**

### Importa o dashboard

1. Grafana → **Dashboards** → **Import**
2. Upload de `dashboards/edgesentinel.json`
3. Seleciona a fonte Prometheus → **Import**

### O que aparece no dashboard

| Painel | O que mostra |
|---|---|
| Temperatura dos sensores | Valores em tempo real por sensor |
| Anomaly score | Score do modelo ML — 0.0 normal, 1.0 anomalia |
| Anomalias detectadas | Taxa de anomalias nos últimos 5 minutos |
| Latência de inferência P95 | 95% das inferências terminam em menos de X ms |
| Latência do pipeline P95 | Tempo total do ciclo completo por sensor |

---

## Métricas expostas

Todas disponíveis em `http://localhost:8000/metrics`:

| Métrica | Tipo | Descrição |
|---|---|---|
| `edgesentinel_sensor_value` | Gauge | Valor atual do sensor |
| `edgesentinel_anomaly_score` | Gauge | Score do modelo ML (0.0 – 1.0) |
| `edgesentinel_anomaly_total` | Counter | Total de anomalias detectadas |
| `edgesentinel_rule_triggered_total` | Counter | Total de disparos de regras |
| `edgesentinel_inference_latency_seconds` | Histogram | Duração por inferência |
| `edgesentinel_pipeline_latency_seconds` | Histogram | Duração do ciclo completo |

---

## Ações disponíveis

| Tipo | O que faz |
|---|---|
| `log` | Escreve no log estruturado com nível configurável |
| `webhook` | POST JSON para qualquer URL (Slack, Discord, PagerDuty, n8n) |
| `gpio_write` | Aciona pino GPIO (LED, relé, buzzer) com duração opcional |

### Payload do webhook

```json
{
  "rule": "alta_temperatura",
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

Para testar o webhook sem servidor, use `https://webhook.site` — gera uma URL gratuita que mostra os payloads em tempo real no browser.

---

## Sensores suportados

| Tipo no config | Fonte Linux | Observações |
|---|---|---|
| `cpu_temperature` | `/sys/class/thermal` ou `vcgencmd` | Detecta Raspberry Pi automaticamente |
| `cpu_usage` | `/proc/stat` | Calculado pela diferença de ticks |
| `memory_usage` | `/proc/meminfo` | Usa `MemAvailable` — mais preciso que `MemFree` |

Para adicionar um novo sensor, implemente `SensorPort` de `core/ports.py` e registre em `adapters/sensors/registry.py`.

---

## Testes

```bash
pip install pytest pytest-mock pytest-cov

# roda todos os testes
pytest tests/ -v

# com relatório de cobertura
pytest tests/ --cov=. --cov-report=term-missing
```

**69 testes, zero falhas.** Inclui unitários, integração e cenários de simulação — todos rodam sem hardware.

| Camada | Cobertura |
|---|---|
| `core/` (domínio) | 100% |
| `application/engine` | 100% |
| `application/pipeline` | 100% |
| `adapters/inference/dummy` | 100% |
| `adapters/inference/onnx` | 88% |
| `adapters/sensors/simulated` | 100% |
| `config/loader` | 95% |

---

## Estrutura do projeto

```
edgesentinel/
├── core/                    # domínio puro — zero dependências externas
│   ├── ports.py             # contratos abstratos
│   ├── entities.py          # dataclasses imutáveis
│   └── rules.py             # Rule e Condition com cooldown
├── config/
│   ├── schema.py            # estrutura do YAML
│   ├── loader.py            # lê e valida config.yaml
│   └── mapper.py            # converte config em objetos do domínio
├── adapters/
│   ├── sensors/             # cpu_temperature, cpu_usage, memory_usage, simulated
│   ├── inference/           # dummy, onnx, tflite
│   ├── actions/             # log, webhook, gpio_write
│   └── exporter/            # Prometheus HTTP /metrics
├── application/
│   ├── engine.py            # RuleEngine
│   ├── pipeline.py          # sense → infer → act
│   └── monitor.py           # loop assíncrono com shutdown gracioso
├── cli/
│   ├── main.py              # run / simulate / doctor
│   ├── builder.py           # monta o sistema a partir do config
│   ├── simulate.py          # sensores simulados
│   └── doctor.py            # diagnóstico do ambiente
├── scripts/
│   └── train_model.py       # treina e exporta modelo ONNX
├── docker/
│   ├── docker-compose.yml   # Prometheus + Grafana
│   └── prometheus.yml       # configuração de scrape
├── dashboards/
│   └── edgesentinel.json    # dashboard Grafana pronto
└── tests/
    ├── core/
    ├── config/
    ├── adapters/
    ├── application/
    └── integration/
```

---

## Roadmap

- [ ] Redis para estado distribuído em deployments multi-dispositivo
- [ ] Ingestão de frames de câmera com YOLO
- [ ] Sensores adicionais: GPIO input, I2C, SPI, BME280
- [ ] Terraform para deployments assistidos por nuvem

---

## Licença

MIT