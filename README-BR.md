# edgesentinel

> Observabilidade inteligente para dispositivos Linux embarcados — sensores,
> modelo de ML local, regras, incidentes e OpenTelemetry, em um processo
> pequeno o bastante para um Raspberry Pi.

Ele lê sensores, pontua as leituras com um modelo local, avalia regras, agrupa
alarmes repetidos em incidentes, guarda o próprio histórico e exporta
métricas — e continua fazendo tudo isso quando a rede cai.

[![tests](https://github.com/diogopelinson/edgesentinel/actions/workflows/tests.yml/badge.svg)](https://github.com/diogopelinson/edgesentinel/actions/workflows/tests.yml)
[![Licença: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Versão 0.3.0](https://img.shields.io/badge/version-0.3.0-orange.svg)](CHANGELOG.md)
[![Docs](https://img.shields.io/badge/docs-Di%C3%A1taxis-green.svg)](docs/README.md)
[![Arquitetura: hexagonal](https://img.shields.io/badge/architecture-hexagonal-lightgrey.svg)](docs/explanation/architecture.md)

[Guia de uso](USAGE-PTBR.md) · [Documentação (inglês)](docs/README.md) · [Roadmap](docs/roadmap.json) · [Changelog](CHANGELOG.md) · [English](README.md)

---

## Índice

- [Por quê](#por-quê)
- [Comece em um minuto](#comece-em-um-minuto)
- [O que ele faz](#o-que-ele-faz)
- [Arquitetura](#arquitetura)
- [Documentação](#documentação)
- [Configuração](#configuração)
- [Stack completa](#stack-completa)
- [Testes](#testes)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Decisões de design](#decisões-de-design)
- [Roadmap](#roadmap)
- [Contribuindo](#contribuindo)
- [Licença](#licença)

---

## Por quê

Monitorar um dispositivo de edge costuma ter duas saídas ruins: mandar as
leituras cruas para outro lugar e ficar cego toda vez que o link cai, ou
escrever um script de shell por dispositivo e descobrir meses depois que
ninguém sabe do que ele alerta.

O edgesentinel é o meio: o dispositivo decide sozinho. As regras são avaliadas
ali, os alertas saem dali, o histórico fica ali, e um endpoint de métricas
espera quem quiser coletar. A rede fora do ar degrada a visão, não o
monitoramento.

- **Não precisa de hardware para experimentar.** O modo de simulação roda o motor real com leituras geradas.
- **Não precisa de servidor para ter histórico.** SQLite, da biblioteca padrão.
- **Detecção de anomalia rodando no dispositivo.** Um modelo ONNX pequeno, não uma API na nuvem.
- **Alarmes repetidos viram incidentes**, com começo, reconhecimento e fim.
- **Arquitetura hexagonal**: sensor, ação ou backend novo é um arquivo novo atrás de uma porta que já existe.

## Comece em um minuto

```bash
git clone https://github.com/diogopelinson/edgesentinel.git
cd edgesentinel
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .[onnx]

edgesentinel doctor                        # o que sua máquina consegue e o que não
edgesentinel simulate --scenario stress    # o pipeline real, sensores simulados
edgesentinel events                        # o que ele registrou
edgesentinel incidents                     # o que continua aberto
```

```
2026-09-23 00:02:57 [INFO] edgesentinel.engine: Incidente #1 aberto para 'uso_alto_cpu' [warning].
2026-09-23 00:02:57 [WARNING] edgesentinel.action.log: Regra 'uso_alto_cpu' disparada | sensor=cpu_usage value=80.44% | anomaly_score=0.9418 threshold=0.7
2026-09-23 00:03:06 [INFO] edgesentinel.engine: Incidente #1 de 'uso_alto_cpu' resolvido em 71.86%.
```

Uma regra disparou, um incidente abriu, a leitura voltou e o incidente fechou
sozinho. O mesmo passo a passo, explicado, está em
[Sua primeira execução sem hardware](docs/tutorials/first-run.md) (em inglês);
em português, o [guia de uso](USAGE-PTBR.md) cobre o mesmo caminho.

## O que ele faz

**Sensores de hardware.** Temperatura e uso de CPU e memória, lidos direto de
`/proc` e `/sys` — sem `psutil`, sem dependência compilada. Sensor cujo
dispositivo não existe se declara indisponível em vez de levantar exceção,
então o mesmo `config.yaml` sobe num Raspberry Pi e num notebook.

**Streams de câmera.** RTSP via MediaMTX, para que uma câmera barata que aceita
duas conexões alimente quantos consumidores forem necessários.

**Inferência de IA em contêiner.** YOLO e modelos ONNX ficam num serviço
separado: se ele cair, o monitoramento de sensores continua.

**Motor de regras.** Comparações numéricas e o operador `anomaly`, apoiado no
modelo local. Cada regra carrega uma severidade — `info`, `warning`,
`critical` — que define o nível de log e chega a todas as ações.

**Incidentes.** O primeiro disparo de uma regra abre um incidente; os seguintes
entram nele; ele fecha sozinho quando o sensor volta, com uma margem que evita
flapping. `edgesentinel incidents` lista os abertos, e `ack` para a repetição do
alerta mantendo o registro — o agente em execução vê isso no ciclo seguinte, sem
sinal e sem restart.

**Histórico local.** Todo disparo vira uma linha em SQLite, gravada por uma
fila e uma thread dedicada — o disco nunca atrasa uma leitura —, consultável no
terminal com `edgesentinel events`.

**OpenTelemetry.** O agente e o AI Service exportam para o mesmo Collector; o
Prometheus coleta e o Grafana mostra dois serviços num painel só.

## Arquitetura

**Ports & adapters**, com uma regra: as dependências apontam para dentro. O
domínio não importa nada — nem SQLite, nem ONNX, nem Prometheus.

```
┌─────────────────────────────────────────────────┐
│                    core/                         │
│  ports.py     → contratos abstratos              │
│  entities.py  → dataclasses imutáveis            │
│  rules.py     → Rule, Condition, Severity        │
│  incidents.py → Incident, IncidentState          │
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
│  store/       → eventos e incidentes (SQLite)    │
│  state/       → cooldown (Redis depois)          │
└─────────────────────────────────────────────────┘
```

É essa regra que faz o `simulate` não ser um mock: ele roda o motor, as regras,
os incidentes, o store e o exporter de verdade, trocando um adapter só.

## Documentação

A documentação longa fica em [docs/](docs/README.md), organizada em
[Diátaxis](https://diataxis.fr/) — tutoriais, guias práticos, referência e
explicação — **em inglês**. Em português, o caminho é o
[guia de uso](USAGE-PTBR.md) e este README.

| Se você quer… | Vá para |
|---|---|
| aprender fazendo | [Tutoriais](docs/tutorials/README.md) |
| resolver uma tarefa | [Guias práticos](docs/how-to/README.md) |
| consultar um detalhe | [Referência](docs/reference/README.md) |
| entender o porquê | [Explicações](docs/explanation/README.md) |
| ver o que foi decidido, e quando | [Registros de decisão](docs/adr/README.md) |

## Configuração

```yaml
edgesentinel:
  poll_interval_seconds: 5

  sensors:
    - id: cpu_temp
      type: cpu_temperature

  inference:
    enabled: true
    backend: onnx
    model_path: models/anomaly.onnx

  exporter:
    port: 8000
    use_otel: false

  event_store:
    enabled: true
    path: data/events.db
    retention_days: 30

  default_actions:              # para regras que não declaram ações próprias
    warning:  [log, webhook]
    critical: [log, webhook, buzzer]

  rules:
    - name: temperatura_critica
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 85.0
        resolve_threshold: 80.0   # onde o incidente fecha; padrão é 10% abaixo
      severity: critical
      cooldown_seconds: 30

  actions:
    - id: log
      type: log
    - id: webhook
      type: webhook
      url: "https://hooks.example.com/alert"
    - id: buzzer
      type: gpio_write
```

Todos os campos, os padrões e tudo o que o loader recusa estão na
[referência de configuração](docs/reference/configuration.md); em português, no
[guia de uso](USAGE-PTBR.md).

## Stack completa

```bash
cd infra/docker
docker compose up -d      # MediaMTX, OTel Collector, Prometheus, Grafana, AI Service
```

Grafana em <http://localhost:3000>, Prometheus em <http://localhost:9090>,
métricas do agente em <http://localhost:8000/metrics>. O dashboard a importar é
`dashboards/edgesentinel_dashboard_v2.json`.

O agente ainda roda no host — colocá-lo em contêiner é a feature
`docker-agent-image` do roadmap.

## Testes

```bash
pip install pytest pytest-mock pytest-cov
pytest tests/ -q
pytest tests/ --cov=core --cov=application --cov-report=term-missing
```

**439 testes, zero falhas**, e nenhum deles precisa de hardware, rede ou
relógio.

| Camada | Cobertura |
|---|---|
| `core/` | 100% |
| `application/engine` | 100% |
| `application/pipeline` | 100% |
| `adapters/state/memory` | 100% |
| `adapters/actions/log` | 100% |
| `config/mapper` | 100% |
| `cli/events` | 99% |
| `config/loader` | 95% |
| `adapters/store/sqlite` | 94% |

O CI reprova se `core/` e `application/` caírem abaixo de **95%** — o piso é
declarado uma vez, no `pyproject.toml`, e um teste exige que esta página cite
o mesmo número. Nos adapters não há piso: cobrir hardware que não existe
seria teatro.

Os testes vêm antes do código, e um teste novo só vale depois de quebrar de
propósito o código que ele cobre — teste que continua verde com o código
quebrado é pior que teste nenhum, porque nele se confia.

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
│   ├── store/                  # SQLite: eventos e incidentes
│   └── state/                  # cooldown (em memória; Redis depois)
├── application/                # RuleEngine, Pipeline, MonitorLoop
├── cli/                        # run / simulate / doctor / events / incidents / ack / resolve
├── ai-inference-service/       # FastAPI com YOLO/ONNX containerizado
├── scripts/                    # train_model.py
├── infra/docker/               # docker-compose, MediaMTX, OTel, Prometheus, Grafana
├── dashboards/                 # edgesentinel_dashboard_v2.json para Grafana
├── docs/                       # tutoriais, guias, referência, explicações, ADRs
├── data/                       # events.db — gerado em execução, fora do git
└── tests/                      # unitários + integração (439 testes)
```

## Decisões de design

Cada uma está registrada por inteiro, com as alternativas que perderam, em
[docs/adr](docs/adr/README.md) (em inglês).

- **[Arquitetura hexagonal](docs/adr/0002-hexagonal-architecture.md)** — o core não conhece infraestrutura: trocar Prometheus por Datadog é um adapter novo, trocar ONNX por TFLite é uma linha de config.
- **[SQLite atrás de uma fila](docs/adr/0003-sqlite-for-the-history.md)** — num cartão SD um `fsync` pode travar centenas de milissegundos, e essa thread é a que lê sensores.
- **[Cooldown atrás de uma porta](docs/adr/0004-cooldowns-behind-a-state-port.md)** — o engine não lê relógio, o que corrigiu uma corrida e é o que torna cooldown distribuído possível.
- **[Score dentro do arquivo do modelo](docs/adr/0005-scoring-inside-the-model-file.md)** — dois serviços constroem a mesma fórmula separadamente; uma definição só, dentro do artefato, impede que discordem.
- **[Incidente fecha com margem](docs/adr/0006-incidents-with-a-resolution-margin.md)** — e um incidente aberto por regra é garantido por índice único parcial, não por lock.
- **[Agente em Python, plano de controle em Go](docs/adr/0007-python-with-go-at-the-edges.md)** — Python onde o lock-in é de ecossistema, Go onde a restrição é de deploy.

Também verdade, e menos arquitetural: `/proc` é lido direto em vez de por
`psutil` (mais leve, explícito, sem dependência compilada), as entidades são
imutáveis porque o loop é async, e o MediaMTX existe porque câmera IP barata
aceita uma ou duas conexões.

## Roadmap

O backlog é um arquivo, não uma lista de desejos:
[docs/roadmap.json](docs/roadmap.json) tem 48 features com dependências,
esforço, status e — nas entregues — o commit que as entregou. O
`tests/test_roadmap.py` mantém isso honesto.

| Marco | O que o fecha |
|---|---|
| v0.2 Fundação de sensores | Qualquer sensor futuro entra sem mexer no schema |
| v0.3 Eventos e severidade | Todo disparo vira evento classificado e consultável ✅ |
| v0.4 Ciclo de incidente | Uma regra passa a ter estado: aberto, reconhecido, resolvido ✅ |
| Saúde do projeto | Documentação, CI, lint, empacotamento, imagem de contêiner |
| v0.5 Visão estruturada | Detecções chegam às regras com bounding boxes e identidade |
| v0.6 Identidade e frota | Dispositivos com identidade, heartbeat e estado compartilhado |
| v0.7 Dashboard próprio | Interface própria, independente do Grafana |
| v0.8 Plataforma | gRPC, versionamento de modelos, atualização remota, Terraform |
| v0.9 Operação em campo | Reload a quente, retentativa, canais de notificação, janelas de manutenção |
| v1.0 Regras compostas | Condições entre sensores e sobre variação no tempo |

Versão atual: **0.3.0** (`edgesentinel --version`).

## Contribuindo

Issues e pull requests são bem-vindos. O [CONTRIBUTING.md](CONTRIBUTING.md)
cobre a configuração do ambiente, o que uma mudança precisa carregar e as
convenções — um arquivo por commit, mensagens em inglês, comentários de código
em português. Agentes de IA têm instruções próprias em [AGENTS.md](AGENTS.md).

Relato de segurança vai pelo [SECURITY.md](SECURITY.md), nunca por issue
público. Esse arquivo também lista o que o agente assume sobre a rede em que
roda, o que vale ler antes de expor um.

## Licença

MIT — veja [LICENSE](LICENSE).
