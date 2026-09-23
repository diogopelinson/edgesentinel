# Run the agent

Starting the agent with and without hardware, and reading what it recorded.

## Check your environment

```bash
edgesentinel doctor
```

Shows what is available on your system — Python, dependencies, sensors, models, cameras and the exporter port.

## Run with real hardware

```bash
edgesentinel run --config config.yaml
edgesentinel run --config config.yaml --log-level DEBUG
```

## Simulate without hardware (Windows / Mac)

```bash
edgesentinel simulate --scenario normal
edgesentinel simulate --scenario stress --interval 1
edgesentinel simulate --scenario spike
```

## Event history

Both `run` and `simulate` record every fired rule in `data/events.db` (SQLite), with a 30-day retention. The path and retention are set in the `event_store` block of `config.yaml`, and `enabled: false` turns history off. To query it from Python, see [Querying the history](use-as-a-library.md#querying-the-history).

## Incidents

The same run also records incidents. The first firing of a rule opens one, every later firing joins it, and it closes when the sensor comes back past the resolution margin — the threshold minus 10%, or `resolve_threshold` when the rule names its own point. Events and incidents share the database, and each event carries the `incident_id` of the episode it belongs to.

There is no `edgesentinel incidents` command yet — listing and acknowledging from the terminal is its own entry in [the roadmap](../roadmap.json). Until then SQLite answers directly:

```bash
# what is open right now
sqlite3 data/events.db "SELECT incident_id, rule_name, state, \
    datetime(opened_at, 'unixepoch', 'localtime') AS opened \
    FROM incidents WHERE state != 'resolved' ORDER BY opened_at;"

# how many firings each episode grouped
sqlite3 data/events.db "SELECT i.incident_id, i.rule_name, COUNT(e.event_id) AS firings \
    FROM incidents i LEFT JOIN events e ON e.incident_id = i.incident_id \
    GROUP BY i.incident_id ORDER BY firings DESC;"

# acknowledge one by hand: the history keeps recording, the actions stop repeating
sqlite3 data/events.db "UPDATE incidents SET state = 'acknowledged', \
    acknowledged_at = strftime('%s', 'now') WHERE incident_id = 7;"
```

The agent picks that acknowledgement up on the next evaluation — it reads the open incidents from the database every time instead of keeping them in memory, which is also why the lifecycle survives a restart with no loading step.

## Query the history

```bash
# what fired in the last hour
edgesentinel events --last 1h

# only critical events from one sensor
edgesentinel events --severity critical --sensor cpu_temp

# another config (and therefore another database)
edgesentinel events --config /etc/edgesentinel/config.yaml -n 100
```

With `--json`, each line is a complete object:

```json
{"event_id": 1162, "time": "2026-09-17T00:35:10-03:00", "timestamp": 1789616110.68, "severity": "warning", "rule_name": "uso_alto_cpu", "sensor_id": "cpu_usage", "value": 92.36, "unit": "%", "anomaly_score": 0.9769}
```

That makes the history easy to script (Linux / macOS):

```bash
# firings per rule over the last 24 hours
edgesentinel events --last 24h --limit 100000 --json | jq -r .rule_name | sort | uniq -c

# external alert if anything critical happened in the last 5 minutes
if edgesentinel events --severity critical --last 5m --json | grep -q .; then
    echo "recent critical"
fi
```

Three guarantees back these uses:

- **stdout holds data only.** "No events found" and errors go to stderr, so the `grep -q .` above only matches real events.
- **Querying changes nothing.** The command applies no retention and does not create the database when it is missing.
- **The exit code tells the cases apart.** `0` for results, no results or an empty history; `1` for an invalid config, a disabled store or an unreadable file; `2` for an invalid option such as `--last yesterday`.

---
