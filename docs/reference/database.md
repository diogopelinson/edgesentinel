# Database

One SQLite file, by default `data/events.db`, holding the rule firings and the
incidents that group them. No server, no extra dependency — the standard
library only. The directory is created when the store opens.

The file is opened in WAL mode, so you will see `events.db-wal` and
`events.db-shm` next to it while the agent runs.

## `events`

One row per rule firing.

```sql
CREATE TABLE events (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     REAL    NOT NULL,     -- epoch seconds of the reading
    rule_name     TEXT    NOT NULL,
    sensor_id     TEXT    NOT NULL,
    value         REAL    NOT NULL,
    unit          TEXT    NOT NULL,
    severity      TEXT    NOT NULL,     -- info | warning | critical
    anomaly_score REAL,                 -- NULL when the rule uses no inference
    incident_id   INTEGER               -- the episode this firing belongs to
);

CREATE INDEX idx_events_timestamp ON events (timestamp);
CREATE INDEX idx_events_severity  ON events (severity, timestamp);
CREATE INDEX idx_events_sensor    ON events (sensor_id, timestamp);
CREATE INDEX idx_events_rule      ON events (rule_name, timestamp);
```

`timestamp` is the time of the **reading**, not of the evaluation. The three
compound indexes exist because every filter the CLI offers ends with a time
window, and a filter plus a window is one index scan rather than two.

`incident_id` is not a foreign key. An event is a fact and must be writable
even when the incident store is failing, so the column can hold `NULL` and
never blocks the insert.

## `incidents`

One row per episode: a rule in alarm from the first firing until it recovers.

```sql
CREATE TABLE incidents (
    incident_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name       TEXT    NOT NULL,
    sensor_id       TEXT    NOT NULL,
    severity        TEXT    NOT NULL,
    state           TEXT    NOT NULL,   -- triggered | acknowledged | resolved
    opened_at       REAL    NOT NULL,
    acknowledged_at REAL,
    resolved_at     REAL
);

CREATE INDEX idx_incidents_state ON incidents (state, opened_at);

CREATE UNIQUE INDEX idx_incidents_one_open_per_rule
    ON incidents (rule_name) WHERE state != 'resolved';
```

That partial unique index is the heart of the grouping: **a rule has at most
one incident that is not resolved.** It is the database that guarantees it, not
the engine — two threads racing to open the same incident produce one row and
one refusal, with no lock anywhere in the application. The refusal is logged
and swallowed, because an incident is context around an alert and must never be
able to silence one.

There is no `normal` state. Normal is the absence of an open row; storing it
would mean a row for every rule that has never fired.

## Writing

`append()` only enqueues. A dedicated thread writes in batches, because
pipelines run on a bounded thread pool and one `fsync` on an SD card can stall
for hundreds of milliseconds. If the queue fills, the event is dropped with a
warning: losing one row of history beats delaying the next alert. On shutdown,
Ctrl+C included, whatever is queued is written before the process exits.

Incidents are written synchronously — opening one has to return its id before
the event that points at it can be written.

## Retention

At startup, events older than `event_store.retention_days` are deleted, and so
are incidents that resolved before the same cut-off. Open incidents are never
pruned, however old they are: an incident that has been open for 40 days is
precisely the one worth keeping.

## Schema versions

The schema version lives in SQLite's own `PRAGMA user_version`, and the store
migrates the file in place when it opens it.

| Version | Shipped with | Contents |
|---|---|---|
| `1` | 0.3.0 | `events` and its indexes |
| `2` | unreleased | adds `incidents`, its indexes, and `events.incident_id` |

A version 1 database is migrated on first open and keeps every event it had;
those events keep `incident_id` empty, because the episodes they belonged to
were never recorded. There is nothing to run by hand.

If you change these tables, bump `_SCHEMA_VERSION` in
`adapters/store/sqlite.py` and add the migration — there are tests that open
databases in the older shape.

## Reading it yourself

The [CLI](cli.md) covers events. Incidents have no command yet, so:

```sql
-- what is open right now
SELECT incident_id, rule_name, state,
       datetime(opened_at, 'unixepoch', 'localtime') AS opened
FROM incidents WHERE state != 'resolved' ORDER BY opened_at;

-- how many firings each episode grouped
SELECT i.incident_id, i.rule_name, COUNT(e.event_id) AS firings
FROM incidents i LEFT JOIN events e ON e.incident_id = i.incident_id
GROUP BY i.incident_id ORDER BY firings DESC;

-- how long the acknowledged ones took to be seen
SELECT incident_id, rule_name,
       ROUND(acknowledged_at - opened_at, 1) AS seconds_to_ack
FROM incidents WHERE acknowledged_at IS NOT NULL;
```

Opening the file while the agent is running is safe — WAL allows one writer and
many readers — and so is acknowledging an incident from another process: the
agent rereads the open incidents on every evaluation.
