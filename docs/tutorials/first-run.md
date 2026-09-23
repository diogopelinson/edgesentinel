# Your first run without hardware

By the end of this you will have the agent installed, simulated sensors being
read, a rule firing, and the firing recorded in a local database you can query.
No Raspberry Pi, no camera, no Docker. About ten minutes.

You need Python 3.10 or newer and git.

> The agent's runtime messages are in Portuguese; the documentation is in
> English. The output below is copied verbatim from a real run, so you can
> compare it with yours character by character.

## 1. Install it

```bash
git clone https://github.com/diogopelinson/edgesentinel.git
cd edgesentinel
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .[onnx]
```

`[onnx]` brings the inference runtime. The bare `pip install -e .` works too —
the agent then runs without anomaly scoring.

## 2. Ask what your machine can do

```bash
edgesentinel doctor
```

```
edgesentinel doctor
====================================================

Python
  OK      Python 3.10.3

Dependências
  OK      pyyaml 6.0.3
  OK      prometheus-client ?
  OK      numpy 2.2.6
  OK      onnxruntime 1.23.2
  AVISO   tflite-runtime — não instalado (opcional)
  AVISO   gpiozero — não instalado (opcional)

Configuração
  OK      config.yaml encontrado em /home/you/edgesentinel/config.yaml
  OK      3 sensor(es) configurado(s)
  OK      3 regra(s) configurada(s)
  OK      2 ação(ões) configurada(s)
  OK      backend de inferência: onnx

Sensores
  AVISO   cpu_temperature      indisponível nesse hardware
  AVISO   cpu_usage            indisponível nesse hardware
  AVISO   memory_usage         indisponível nesse hardware
```

Those three warnings are the point of this tutorial. On a laptop running
Windows or macOS there is no `/sys/class/thermal` and no `/proc/stat`, so the
real sensors report themselves unavailable instead of crashing the agent. On
Linux you will see `OK` there instead — either way, the next step behaves the
same.

## 3. Run it with simulated sensors

```bash
edgesentinel simulate --scenario stress --interval 1
```

The `stress` scenario ramps temperature and CPU usage upwards until rules start
firing. Within a minute you should see something like this:

```
2026-09-23 00:02:56 [INFO] edgesentinel.exporter: Prometheus exporter ativo em http://0.0.0.0:8000/metrics
2026-09-23 00:02:56 [INFO] edgesentinel.store: Event Store aberto em data/events.db
2026-09-23 00:02:57 [INFO] edgesentinel.engine: Incidente #1 aberto para 'uso_alto_cpu' [warning].
2026-09-23 00:02:57 [INFO] edgesentinel.engine: Regra 'uso_alto_cpu' [warning] disparada para sensor 'cpu_usage'.
2026-09-23 00:02:57 [WARNING] edgesentinel.action.log: Regra 'uso_alto_cpu' disparada | sensor=cpu_usage value=80.44% | anomaly_score=0.9418 threshold=0.7
2026-09-23 00:03:06 [INFO] edgesentinel.engine: Incidente #1 de 'uso_alto_cpu' resolvido em 71.86%.
```

Read those five lines closely, because they are the whole system:

- the **exporter** is already serving metrics — open <http://localhost:8000/metrics> in a browser while it runs;
- the **store** opened the database that will hold the history;
- the **engine** opened an incident *before* dispatching the action: the first firing of a rule starts an episode;
- the **action** logged the firing with the value, the anomaly score and the threshold;
- nine seconds later the reading came back down far enough and the incident **resolved by itself**.

Leave it running for a minute, then stop it with Ctrl+C. It shuts down
gracefully: whatever is queued for the history is written before the process
exits.

## 4. Look at what it recorded

```bash
edgesentinel events
```

```
QUANDO               SEVERIDADE  REGRA         SENSOR       VALOR  SCORE
2026-09-23 00:02:57  WARNING     uso_alto_cpu  cpu_usage  80.44 %   0.94

1 evento(s)
```

The same history in one JSON object per line, which is what you would pipe into
`jq` or a script:

```bash
edgesentinel events --limit 1 --json
```

```json
{"event_id": 1, "time": "2026-09-23T00:02:57-03:00", "timestamp": 1790132577.4297056, "severity": "warning", "rule_name": "uso_alto_cpu", "sensor_id": "cpu_usage", "value": 80.44, "unit": "%", "anomaly_score": 0.9418, "incident_id": 1}
```

Two details worth noticing. `incident_id` points at the episode from step 3 —
every firing of that rule while the incident was open carries the same id. And
filtering something out is not an error:

```bash
edgesentinel events --severity critical
```

```
Nenhum evento encontrado com esses filtros.
```

That message went to stderr, not stdout, and the exit code is still `0`. It
means `edgesentinel events --json | jq` never receives loose text, and a script
can tell "nothing matched" from "something went wrong" by the exit code.

## What you just saw

A sensor was read, the reading was scored by a local ONNX model, a rule matched
it, an incident opened, an action ran, a row was written to SQLite and a metric
was exported — the entire pipeline, on a machine with no sensors in it.

Nothing here was special-cased for simulation. `edgesentinel run` on a Raspberry
Pi executes the same code with a different `SensorPort` implementation behind
it; that is what the architecture is for.

## Next

- [Watching an incident open and close](first-incident.md) — write your own rule and drive the incident through its states.
- [Run the agent](../how-to/run-the-agent.md) — the other scenarios, real hardware, and querying the history properly.
- [Configuration reference](../reference/configuration.md) — every field in `config.yaml`.
