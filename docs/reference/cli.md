# Command line

```
edgesentinel [--version] {run,simulate,doctor,events,incidents,ack,resolve} [options]
```

Installing the package puts `edgesentinel` on the path. `python -m cli.main`
does the same thing and is the way out when a venv's console scripts break —
they embed the absolute path of the directory the venv was created in.

Every subcommand takes `--config/-c PATH` (default `config.yaml`) and
`--log-level/-l {DEBUG,INFO,WARNING,ERROR}`. The default level is `INFO` for
`run` and `simulate`, `WARNING` for `doctor` and `events`.

## `run`

Starts monitoring with the sensors declared in the config, on real hardware.

```bash
edgesentinel run
edgesentinel run --config /etc/edgesentinel/config.yaml --log-level DEBUG
```

Runs until interrupted. Ctrl+C shuts down gracefully: the queued history is
written before the process exits. A missing config file or an invalid one
prints the reason and exits `1`.

## `simulate`

The same pipeline — inference, rules, incidents, actions, metrics, history —
driven by generated readings instead of hardware.

```bash
edgesentinel simulate --scenario stress --interval 1
```

| Option | Default | Meaning |
|---|---|---|
| `--scenario/-s {normal,stress,spike}` | `normal` | Which curve the simulated sensors follow |
| `--interval/-i SECONDS` | `2.0` | Seconds between ticks |

| Scenario | What it does |
|---|---|
| `normal` | Steady values inside the expected band. Nothing fires |
| `stress` | Temperature and CPU climb progressively until rules fire |
| `spike` | Quiet, with a sharp spike roughly every twenty seconds |

The sensors come from the scenario, not from the config: `simulate` always
drives `cpu_temp`, `cpu_usage` and `memory_usage`. Everything else — rules,
actions, inference, the event store — is read from your config file, which is
what makes it a real test of a rule you are about to deploy.

## `doctor`

Inspects the environment and reports what works, what is missing and what the
missing piece would have enabled. It changes nothing.

```bash
edgesentinel doctor
```

It covers the Python version, the optional dependencies, the config file and
what it declares, which sensors are actually available on this machine, and
which inference backends can be built. Paste its output into a bug report.

## `incidents`

Lists incidents. Open ones by default, newest first.

```bash
edgesentinel incidents
edgesentinel incidents --all --last 24h
edgesentinel incidents --severity critical --json
```

```
#  ESTADO     SEVERIDADE  REGRA  SENSOR    ABERTO               DURAÇÃO  DISPAROS
1  TRIGGERED  WARNING     hot    cpu_temp  2026-09-23 23:49:50  5s              3

1 incidente(s) aberto(s)
```

| Option | Effect |
|---|---|
| `--all/-a` | Include resolved incidents |
| `--severity/-s {info,warning,critical}` | Only that level |
| `--rule/-r NAME` | Only that rule |
| `--last DURATION` | Opened within this window: `30m`, `24h`, `7d` |
| `--limit/-n N` | At most N incidents, newest first. Default 20 |
| `--json` | One JSON object per line |

`DURAÇÃO` is time since it opened for an open incident, and total lifetime for a
resolved one. `DISPAROS` is how many firings the incident grouped — the column
that shows what grouping bought.

### The JSON record

```json
{"incident_id": 1, "state": "resolved", "severity": "warning", "rule_name": "hot", "sensor_id": "cpu_temp", "opened": "2026-09-23T23:49:50-03:00", "opened_at": 1790218190.0679913, "acknowledged_at": 1790218196.6063614, "resolved_at": 1790218200.237579, "duration_seconds": 10.17, "firings": 3}
```

## `ack`

Acknowledges an incident: someone has seen it, so the actions stop repeating
while the history keeps recording.

```bash
edgesentinel ack 7
```

```
Incidente #1 de 'hot' [warning] reconhecido após 6s aberto.
O agente para de repetir as ações dessa regra no próximo ciclo; os disparos continuam indo para o histórico.
```

The running agent needs no signal and no restart: it rereads the open incidents
on every evaluation, so the change lands on its next cycle. That is also why
this works while the agent is writing to the same database.

Acknowledging twice is not an error — a script that acknowledges an id should
not fail because someone got there first. Acknowledging a **resolved** incident
is refused: the cycle does not go backwards, and the next firing opens a new
incident instead.

## `resolve`

Closes an incident by hand, without waiting for the reading to come back past
the margin.

```bash
edgesentinel resolve 7
```

An acknowledged incident can be resolved; resolving twice is not an error. After
it is resolved, the next firing of that rule opens a different incident.

### Exit codes for both

| Code | Meaning |
|---|---|
| `0` | Done, or already in that state |
| `1` | Bad config, disabled store, no database, unknown id, or a transition the cycle forbids |
| `2` | An invalid option, such as `ack 0` |

```
$ edgesentinel ack 4242
Erro: não existe incidente #4242. Use 'edgesentinel incidents' para ver os abertos.
```

## `events`

Reads the history. It never prunes and never creates the database.

```bash
edgesentinel events                                   # 20 most recent
edgesentinel events --severity critical --last 24h
edgesentinel events --rule high_temperature -n 50
edgesentinel events --sensor cpu_temp --json | jq .value
```

| Option | Effect |
|---|---|
| `--severity/-s {info,warning,critical}` | Only that level |
| `--sensor ID` | Only that sensor |
| `--rule/-r NAME` | Only that rule |
| `--last DURATION` | Window ending now: `30m`, `24h`, `7d` (`s`, `m`, `h`, `d`) |
| `--limit/-n N` | At most N events, newest first. Default 20 |
| `--json` | One JSON object per line |

### The JSON record

```json
{"event_id": 1, "time": "2026-09-23T00:02:57-03:00", "timestamp": 1790132577.4297056, "severity": "warning", "rule_name": "uso_alto_cpu", "sensor_id": "cpu_usage", "value": 80.44, "unit": "%", "anomaly_score": 0.9418, "incident_id": 1}
```

`time` is local with an offset, `timestamp` is the raw epoch seconds, and
`anomaly_score` and `incident_id` are `null` when the event has neither.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Results, no matches, or no history yet |
| `1` | Bad config, a disabled store, or an unreadable database |
| `2` | An invalid option, such as `--last yesterday` |

Data goes to stdout and status messages to stderr, so `--json | jq` never
receives loose text and "nothing matched" is distinguishable from "something
broke" by the exit code alone.

## Not here yet

No command exports the history to CSV, and none edits the config. Metrics for
incidents — open by severity, time to acknowledge — are not exported either;
that is `incident-metrics` in [the roadmap](../roadmap.json).
