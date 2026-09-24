# edgesentinel

> Intelligent observability for Linux embedded devices — sensors, a local ML
> model, rules, incidents and OpenTelemetry, in one process small enough for a
> Raspberry Pi.

It reads sensors, scores them with a local model, evaluates rules, groups
repeated alarms into incidents, keeps its own history and exports metrics —
and it keeps doing all of that when the network is gone.

[![tests](https://github.com/diogopelinson/edgesentinel/actions/workflows/tests.yml/badge.svg)](https://github.com/diogopelinson/edgesentinel/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Version 0.3.0](https://img.shields.io/badge/version-0.3.0-orange.svg)](CHANGELOG.md)
[![Docs](https://img.shields.io/badge/docs-Di%C3%A1taxis-green.svg)](docs/README.md)
[![Architecture: hexagonal](https://img.shields.io/badge/architecture-hexagonal-lightgrey.svg)](docs/explanation/architecture.md)

[Documentation](docs/README.md) · [Usage guide](USAGE-EN.md) · [Roadmap](docs/roadmap.json) · [Changelog](CHANGELOG.md) · [Português](README-BR.md)

---

## Contents

- [Why](#why)
- [Quickstart](#quickstart)
- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Documentation](#documentation)
- [Configuration](#configuration)
- [Full stack](#full-stack)
- [Tests](#tests)
- [Project structure](#project-structure)
- [Design decisions](#design-decisions)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Why

Monitoring an edge device usually means one of two bad options: ship the raw
readings somewhere else and be blind whenever the link drops, or write a shell
script per device and discover months later that nobody knows what it alerts
on.

edgesentinel is the middle: the device decides for itself. Rules are evaluated
locally, alerts are dispatched locally, the history is stored locally, and a
metrics endpoint is offered to whatever wants to scrape it. The network being
down degrades the view, not the monitoring.

- **No hardware needed to try it.** A simulation mode runs the real engine against generated readings.
- **No server needed to keep history.** SQLite, in the standard library.
- **Anomaly detection that runs on the device.** A small ONNX model, not a cloud API.
- **Repeated alarms become incidents** with a beginning, an acknowledgement and an end.
- **Hexagonal architecture**, so a new sensor, action or backend is a new file behind an existing port.

## Quickstart

```bash
git clone https://github.com/diogopelinson/edgesentinel.git
cd edgesentinel
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .[onnx]

edgesentinel doctor                        # what your machine can and cannot do
edgesentinel simulate --scenario stress    # the real pipeline, simulated sensors
edgesentinel events                        # what it recorded
```

```
2026-09-23 00:02:57 [INFO] edgesentinel.engine: Incidente #1 aberto para 'uso_alto_cpu' [warning].
2026-09-23 00:02:57 [WARNING] edgesentinel.action.log: Regra 'uso_alto_cpu' disparada | sensor=cpu_usage value=80.44% | anomaly_score=0.9418 threshold=0.7
2026-09-23 00:03:06 [INFO] edgesentinel.engine: Incidente #1 de 'uso_alto_cpu' resolvido em 71.86%.
```

A rule fired, an incident opened, the reading came back down and the incident
closed itself. Step by step, with everything explained:
[Your first run without hardware](docs/tutorials/first-run.md).

## What it does

**Hardware sensors.** CPU temperature, CPU usage and memory, read straight from
`/proc` and `/sys` — no `psutil`, no compiled dependency. A sensor whose device
is missing reports itself unavailable instead of raising, so the same
`config.yaml` starts on a Raspberry Pi and on a laptop.

**Camera streams.** RTSP through MediaMTX, so a cheap camera that accepts two
connections can feed any number of consumers.
→ [Connect a real camera](docs/how-to/connect-a-camera.md)

**Containerised AI inference.** YOLO and ONNX models live in a separate
service, so a crash there never stops sensor monitoring.
→ [Run the AI Inference Service](docs/how-to/run-the-ai-service.md)

**Rule engine.** Numeric comparisons and an `anomaly` operator backed by the
local model. Each rule carries a severity — `info`, `warning`, `critical` —
that sets the log level and reaches every action.

**Incidents.** The first firing of a rule opens an incident; later firings join
it; it closes on its own when the sensor recovers, with a margin that prevents
flapping. Acknowledging stops the alerts and keeps the recording.
→ [Incidents and hysteresis](docs/explanation/incidents.md)

**Local history.** Every firing becomes a row in SQLite, written by a queue and
a dedicated thread so the disk never delays a reading, and queryable from the
terminal with `edgesentinel events`.
→ [Database reference](docs/reference/database.md)

**Actions.** `log`, `webhook` and `gpio_write`, selectable per rule or once per
severity. An action that fails is logged and swallowed: the next one still
runs.

**OpenTelemetry.** The agent and the AI Service export to the same Collector;
Prometheus scrapes and Grafana plots two services on one dashboard.
→ [Metrics reference](docs/reference/metrics.md)

## Architecture

**Ports and adapters**, with one rule: dependencies point inward. The domain
imports nothing — not SQLite, not ONNX, not Prometheus.

```
┌─────────────────────────────────────────────────┐
│                    core/                         │
│  ports.py     → abstract contracts              │
│  entities.py  → immutable dataclasses           │
│  rules.py     → Rule, Condition, Severity       │
│  incidents.py → Incident, IncidentState         │
└───────────────────────┬─────────────────────────┘
                        │ everything depends on core
┌───────────────────────▼─────────────────────────┐
│                 application/                     │
│  engine.py    → evaluates rules, dispatches     │
│  pipeline.py  → sense → infer → act per sensor  │
│  monitor.py   → async loop with graceful shutdown│
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│                  adapters/                       │
│  sensors/     → hardware, camera, simulated      │
│  inference/   → dummy, onnx, tflite, remote      │
│  actions/     → log, webhook, gpio               │
│  exporter/    → legacy Prometheus + OTel         │
│  store/       → events and incidents (SQLite)    │
│  state/       → cooldowns (Redis later)          │
└─────────────────────────────────────────────────┘
```

That rule is why `simulate` is not a mock: it runs the real engine, rules,
incidents, store and exporter with one adapter swapped.
→ [Architecture, and what it costs](docs/explanation/architecture.md)

## Documentation

| If you want to… | Start at |
|---|---|
| learn by doing | [Tutorials](docs/tutorials/README.md) |
| get something done | [How-to guides](docs/how-to/README.md) |
| look something up | [Reference](docs/reference/README.md) |
| understand why | [Explanation](docs/explanation/README.md) |
| see what was decided, and when | [Decision records](docs/adr/README.md) |

The long-form usage guide is still at [USAGE-EN.md](USAGE-EN.md) (and
[USAGE-PTBR.md](USAGE-PTBR.md) in Portuguese).

## Configuration

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

  default_actions:              # for rules that declare no actions of their own
    warning:  [log, webhook]
    critical: [log, webhook, buzzer]

  rules:
    - name: critical_temperature
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 85.0
        resolve_threshold: 80.0   # where the incident closes; default is 10% below
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

Every field, every default and everything the loader refuses:
→ [Configuration reference](docs/reference/configuration.md)

## Full stack

```bash
cd infra/docker
docker compose up -d      # MediaMTX, OTel Collector, Prometheus, Grafana, AI Service
```

Grafana at <http://localhost:3000>, Prometheus at <http://localhost:9090>, the
agent's metrics at <http://localhost:8000/metrics>. The dashboard to import is
`dashboards/edgesentinel_dashboard_v2.json`.
→ [Set up Prometheus and Grafana](docs/how-to/set-up-observability.md)

The agent itself still runs on the host — containerising it is
`docker-agent-image` in the roadmap.

## Tests

```bash
pip install pytest pytest-mock pytest-cov
pytest tests/ -q
pytest tests/ --cov=core --cov=application --cov-report=term-missing
```

**380 tests, zero failures**, none of which need hardware, a network or a
clock.

| Layer | Coverage |
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

Tests are written before the code, and a new test is checked by breaking the
code it covers on purpose — a test that stays green against broken code is
worse than no test, because it is believed.

## Project structure

```
edgesentinel/
├── core/                       # pure domain — zero external dependencies
├── config/                     # YAML loader and schema
├── adapters/
│   ├── sensors/                # cpu_temp, cpu_usage, memory, camera, simulated
│   ├── inference/              # dummy, onnx, tflite, remote (AI Service)
│   ├── actions/                # log, webhook, gpio
│   ├── exporter/               # legacy Prometheus + OpenTelemetry
│   ├── store/                  # SQLite: events and incidents
│   └── state/                  # cooldowns (in-memory; Redis later)
├── application/                # RuleEngine, Pipeline, MonitorLoop
├── cli/                        # run / simulate / doctor / events
├── ai-inference-service/       # FastAPI with containerized YOLO/ONNX
├── scripts/                    # train_model.py
├── infra/docker/               # docker-compose, MediaMTX, OTel, Prometheus, Grafana
├── dashboards/                 # edgesentinel_dashboard_v2.json for Grafana
├── docs/                       # tutorials, how-to, reference, explanation, ADRs
├── data/                       # events.db — created at runtime, not tracked
└── tests/                      # unit + integration (380 tests)
```

## Design decisions

Each of these is recorded in full, with the alternatives that lost, in
[docs/adr](docs/adr/README.md).

- **[Hexagonal architecture](docs/adr/0002-hexagonal-architecture.md)** — the core knows no infrastructure, so swapping Prometheus for Datadog is a new adapter and swapping ONNX for TFLite is a config line.
- **[SQLite behind a queue](docs/adr/0003-sqlite-for-the-history.md)** — on an SD card one `fsync` can stall for hundreds of milliseconds, and that thread is the one reading sensors.
- **[Cooldowns behind a port](docs/adr/0004-cooldowns-behind-a-state-port.md)** — the engine never reads a clock, which fixed a race and is what makes distributed cooldowns possible at all.
- **[Scoring inside the model file](docs/adr/0005-scoring-inside-the-model-file.md)** — two services build the same formula separately; one definition in the artifact means they cannot disagree.
- **[Incidents close on a margin](docs/adr/0006-incidents-with-a-resolution-margin.md)** — and one open incident per rule is enforced by a partial unique index, not by a lock.
- **[Python agent, Go control plane](docs/adr/0007-python-with-go-at-the-edges.md)** — Python where the ecosystem is the constraint, Go where deployment is.

Also true and less architectural: `/proc` is read directly rather than through
`psutil` (lighter, explicit, no compiled dependency), entities are frozen
because the loop is async, and MediaMTX exists because cheap IP cameras accept
one or two connections.

## Roadmap

The backlog is a file, not a wish list: [docs/roadmap.json](docs/roadmap.json)
holds 48 features with their dependencies, effort, status and — for delivered
ones — the commit that delivered them. `tests/test_roadmap.py` keeps it honest.

| Milestone | What closes it |
|---|---|
| v0.2 Sensor foundation | Any future sensor can be added without touching the schema |
| v0.3 Events and severity | Every firing is a stored, classified, queryable event ✅ |
| v0.4 Incident cycle | A rule has state: open, acknowledged, resolved ✅ |
| Project health | Docs, CI, linting, packaging, a container image |
| v0.5 Structured vision | Detections reach the rules with boxes and identity |
| v0.6 Identity and fleet | Devices have identity, heartbeat and shared state |
| v0.7 Own dashboard | An interface of its own, independent of Grafana |
| v0.8 Platform | gRPC, model versioning, OTA updates, Terraform |
| v0.9 Field operation | Hot reload, retries, notification channels, maintenance windows |
| v1.0 Composite rules | Conditions across sensors, and rates of change |

Current version: **0.3.0** (`edgesentinel --version`).

## Contributing

Issues and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers
setup, what a change is expected to carry and the conventions — one file per
commit, English commit messages, Portuguese code comments. AI coding agents
have their own instructions in [AGENTS.md](AGENTS.md).

Security reports go through [SECURITY.md](SECURITY.md), never a public issue.
That file also lists what the agent assumes about the network it runs in, which
is worth reading before exposing one.

## License

MIT — see [LICENSE](LICENSE).
