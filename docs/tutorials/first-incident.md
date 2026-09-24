# Watching an incident open and close

In [the first tutorial](first-run.md) an incident opened and closed on its own
while you watched. Here you write the rule that causes it, drive the incident
through all three of its states, and see why it closes where it does. About
fifteen minutes.

Start from a working installation — the first tutorial gets you there.

## 1. A rule of your own

Create `tutorial.yaml` next to `config.yaml`:

```yaml
edgesentinel:
  poll_interval_seconds: 2

  sensors:
    - id: cpu_temp
      type: cpu_temperature

  inference:
    enabled: false

  event_store:
    path: data/tutorial.db

  rules:
    - name: hot
      condition:
        sensor_id: cpu_temp
        operator: ">"
        threshold: 58.0
        resolve_threshold: 56.0
      severity: warning
      cooldown_seconds: 0
      actions: [log]

  actions:
    - id: log
      type: log
```

Three of those values are deliberate and everything in this tutorial depends on
them:

- `cooldown_seconds: 0` — normally a rule waits before firing again. Zero means
  every matching reading fires, which is what makes the grouping visible.
- `resolve_threshold: 56.0` — the incident does not close at 58, the value that
  opened it. It closes two degrees lower.
- a separate `event_store.path` — your history from the first tutorial stays
  untouched in `data/events.db`.

## 2. Watch the incident open

```bash
edgesentinel simulate --scenario spike --config tutorial.yaml --interval 1
```

The `spike` scenario holds the temperature near 55 °C and throws a spike every
twenty seconds or so — an episode with a beginning and an end, which is exactly
what an incident is meant to describe.

```
[tick 001]
  CPU Temperature        80.28 °C
2026-09-23 23:55:32 [INFO] edgesentinel.engine: Incidente #1 aberto para 'hot' [warning].
2026-09-23 23:55:32 [INFO] edgesentinel.engine: Regra 'hot' [warning] disparada para sensor 'cpu_temp'.
2026-09-23 23:55:32 [WARNING] edgesentinel.action.log: Regra 'hot' disparada | sensor=cpu_temp value=80.28°C
  CPU Usage              40.05 %
  Memory Usage           50.17 %
```

Three lines, three different things: the incident opened, the rule fired, the
action ran. The order matters — the incident exists before the alert goes out,
so every alert can point at the episode it belongs to.

Leave it running and go to the next step in a second terminal.

## 3. Acknowledge it

Acknowledging means "I have seen this, stop telling me" — the problem is still
happening, so the history must keep recording it, but the actions stop firing.
With the agent still running, in the second terminal:

```bash
edgesentinel incidents --config tutorial.yaml
```

```
#  ESTADO     SEVERIDADE  REGRA  SENSOR    ABERTO               DURAÇÃO  DISPAROS
1  TRIGGERED  WARNING     hot    cpu_temp  2026-09-23 23:55:32  1s              2

1 incidente(s) aberto(s)
```

Two firings already grouped under incident 1, one second old. Acknowledge it by
id:

```bash
edgesentinel ack 1 --config tutorial.yaml
```

```
Incidente #1 de 'hot' [warning] reconhecido após 1s aberto.
O agente para de repetir as ações dessa regra no próximo ciclo; os disparos continuam indo para o histórico.
```

Now watch the terminal where the agent is running. The spike is still going,
so the rule matches again two seconds later:

```
[tick 003]
  CPU Temperature        80.96 °C
2026-09-23 23:55:34 [INFO] edgesentinel.engine: Regra 'hot' [warning] disparada para sensor 'cpu_temp'.
  CPU Usage              43.75 %
  Memory Usage           52.39 %
```

Compare it with tick 001. The rule fired — the `INFO` line is there and the
event was written — but the `WARNING` line from the log action is gone. The
alert stopped repeating; the record did not.

Nothing was restarted and nothing was signalled. The agent picked your
acknowledgement up because it reads the open incidents from the database on
every evaluation instead of keeping them in memory. The same mechanism is why
the lifecycle survives a restart.

## 4. Watch it close by itself

Keep watching. When the spike passes:

```
[tick 010]
  CPU Temperature        55.76 °C
2026-09-23 23:55:42 [INFO] edgesentinel.engine: Incidente #1 de 'hot' resolvido em 55.76°C.
  CPU Usage              41.76 %
  Memory Usage           51.06 %
```

An acknowledged incident still resolves: acknowledging says someone is on it,
not that the problem is over. Now stop the agent with Ctrl+C.

## 5. Look at the episodes

`incidents` shows the open ones; `--all` includes what already closed:

```bash
edgesentinel incidents --all --config tutorial.yaml
```

```
#  ESTADO     SEVERIDADE  REGRA  SENSOR    ABERTO               DURAÇÃO  DISPAROS
4  TRIGGERED  WARNING     hot    cpu_temp  2026-09-23 23:56:18  1s              1
3  RESOLVED   WARNING     hot    cpu_temp  2026-09-23 23:56:13  2s              2
2  RESOLVED   WARNING     hot    cpu_temp  2026-09-23 23:55:53  10s             6
1  RESOLVED   WARNING     hot    cpu_temp  2026-09-23 23:55:32  9s              5

4 incidente(s)
```

Four spikes, four incidents, fourteen firings grouped under them — and the
twenty seconds between one episode and the next are visible in the timestamps.
Without incidents this would be fourteen independent alerts, with nothing saying
which ones described the same event. Incident 4 is still `TRIGGERED` because the
spike was in progress when the agent stopped; incident 3 lasted two seconds,
which is what a spike that barely crossed the threshold looks like.

`--json` gives the same rows one object per line, including the
`acknowledged_at` of the one you acknowledged:

```bash
edgesentinel incidents --all --json --config tutorial.yaml
```

```json
{"incident_id": 1, "state": "resolved", "severity": "warning", "rule_name": "hot", "sensor_id": "cpu_temp", "opened": "2026-09-23T23:55:32-03:00", "opened_at": 1790218532.7863784, "acknowledged_at": 1790218534.6851783, "resolved_at": 1790218542.0397637, "duration_seconds": 9.253, "firings": 5}
```

`acknowledged_at` is filled in and `resolved_at` came nine seconds after it
opened: the whole episode, in one row.

## 6. Why 56 and not 58

Delete the `resolve_threshold` line from `tutorial.yaml` and run it again. It
still works — the incident now closes at **52.2 °C**, which is 58 minus ten
percent of 58, away from the alarm.

That gap is the whole point. If an incident closed at the value that opened it,
a temperature hovering at 58.0 would close and reopen an incident on every
single reading, and you would get a stream of "opened" and "resolved" messages
describing one unchanging situation. The distance is called hysteresis; ten
percent is the default because it is large enough to absorb sensor noise and
small enough that a genuine recovery still closes the incident promptly.

`resolve_threshold` is for when ten percent is the wrong distance. The loader
refuses a value on the alarm side of the threshold — `> 58` resolving at 60
would close the incident while the sensor is still too hot — so the mistake
fails at startup rather than in the field.

## What you just saw

Three states, one episode, and a closing rule that keeps the episode stable.
The state lives in SQLite rather than in the process, which is what let another
program acknowledge an incident that a running agent was still updating.

## Next

- [Incidents and hysteresis](../explanation/incidents.md) — why it is built this way.
- [Configuration reference](../reference/configuration.md) — every field you can put in a rule.
- [Query the history](../how-to/run-the-agent.md) — filters, JSON output and scripting.
