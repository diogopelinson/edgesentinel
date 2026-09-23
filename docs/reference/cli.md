# Command line

```
edgesentinel [--version] {run,simulate,doctor,events} [options]
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

There is no `incidents` command: listing, acknowledging and resolving from the
terminal is `cli-incidents-ack` in [the roadmap](../roadmap.json). Until it
lands, the SQL is in [Run the agent](../how-to/run-the-agent.md).
