# Metrics

Exact names as they appear in Prometheus and Grafana. Use them verbatim in
PromQL; the agent does not rename anything per backend.

## The agent

Served on `exporter.port` at `/metrics`, or sent to an OTel Collector when
`exporter.use_otel` is true. The names are the same either way.

| Metric | Type | Labels | What it holds |
|---|---|---|---|
| `edgesentinel_sensor_value` | Gauge | `sensor_id`, `sensor_name`, `unit` | The last reading, in the sensor's own unit |
| `edgesentinel_anomaly_score` | Gauge | `sensor_id`, `model_id` | The model's score for that reading, 0.0 to 1.0 |
| `edgesentinel_anomaly_total` | Counter | `sensor_id`, `model_id` | Readings the model called anomalous |
| `edgesentinel_pipeline_latency_seconds` | Histogram | `sensor_id` | Read, score, evaluate and dispatch, end to end |
| `edgesentinel_inference_latency_seconds` | Histogram | `model_id` | Time inside the model only |
| `edgesentinel_incidents_open` | Gauge | `rule`, `severity`, `state` | Incidents open right now |
| `edgesentinel_incidents_total` | Counter | `rule`, `severity`, `transition` | Lifecycle transitions this agent made |
| `edgesentinel_incident_duration_seconds` | Histogram | `severity` | How long each closed incident lasted |

Two of those repay attention. `edgesentinel_pipeline_latency_seconds` includes
the actions, so a slow webhook shows up here rather than anywhere else — this
is how you notice that an alert path is dragging the loop. And
`edgesentinel_anomaly_score` is a gauge over the raw score, not over the
rule's verdict: it moves even while nothing is firing, which is what makes a
threshold easy to choose from the graph.

## Incidents

These three are not symmetrical, and the asymmetry is worth understanding
before you build a panel on them.

**`edgesentinel_incidents_open` is read from the database on every scrape.** It
is not accumulated in the process, because a counter kept in memory would be
wrong in the two cases that matter: after a restart, when the incident is still
open on disk, and after an acknowledgement made with `edgesentinel ack`, which
runs in a different process. Reading the store means the gauge is correct in
both, with no reconciliation step. It also means the series is **sparse**: with
nothing open, no labels are published at all, so a `sum()` over it returns
empty rather than zero. Write `sum(edgesentinel_incidents_open) or vector(0)`
in any panel that should show a number.

The `state` label carries `triggered` or `acknowledged` — `resolved` never
appears, because a resolved incident is not open. That is what makes
`edgesentinel_incidents_open{state="triggered"}` expressible, and it is the
number that asks for action: an acknowledged incident already has someone on
it.

**`edgesentinel_incidents_total` and `edgesentinel_incident_duration_seconds`
count what the agent did.** They are process counters, which is deliberate:
deriving them from the table would break monotonicity, since `prune()` deletes
resolved incidents once past the retention window and Prometheus would read
every retention cycle as a counter reset. The cost of that choice is stated
plainly: `transition` takes `opened` and `resolved` and nothing else, because
an acknowledgement happens in the CLI, in another process with no metrics
endpoint. An `ack` moves the gauge on the next scrape and never reaches the
counter, and a `resolve` done from the CLI likewise never reaches the
histogram. The durations you see are the incidents the agent closed on its own.

If the database cannot be read during a scrape — a locked SQLite file is
ordinary on an SD card — the gauge publishes nothing for that scrape and the
error goes to the agent log. The failure is swallowed on purpose: an exception
inside a scrape drops every other metric on the endpoint with it.

## The AI Inference Service

Served by the container, on its own port.

| Metric | Type | Labels | What it holds |
|---|---|---|---|
| `ai_service_inference_total` | Counter | `model_id` | Inference requests served |
| `ai_service_inference_latency_ms_milliseconds` | Histogram | `model_id` | Latency per inference, in milliseconds |
| `ai_service_detections_total` | Counter | `model_id` | Objects returned across all inferences |

The doubled unit in `ai_service_inference_latency_ms_milliseconds` is not a
typo in this page: the instrument is named `..._ms` and the exporter appends
the unit. Query it exactly as written.

## Useful queries

```promql
# every sensor's current value
edgesentinel_sensor_value

# anomaly score by sensor
edgesentinel_anomaly_score

# anomaly rate over the last five minutes
rate(edgesentinel_anomaly_total[5m])

# p95 of the whole pipeline, per sensor
histogram_quantile(0.95, rate(edgesentinel_pipeline_latency_seconds_bucket[5m]))

# p95 of the AI Service, in milliseconds
histogram_quantile(0.95, rate(ai_service_inference_latency_ms_milliseconds_bucket[5m]))

# inferences per second, per model
rate(ai_service_inference_total[1m])

# how many incidents are open, zero included
sum(edgesentinel_incidents_open) or vector(0)

# open and nobody has acknowledged them yet
sum(edgesentinel_incidents_open{state="triggered"}) or vector(0)

# open by severity, for a stacked graph
sum by (severity) (edgesentinel_incidents_open)

# which rules are in alarm, and in which state
sum by (rule, state) (edgesentinel_incidents_open)

# incidents opened per minute
sum(rate(edgesentinel_incidents_total{transition="opened"}[5m])) * 60

# p95 of how long an incident lasts, by severity
histogram_quantile(0.95, sum by (le, severity)
  (rate(edgesentinel_incident_duration_seconds_bucket[30m])))

# mean duration over the last hour, in seconds
sum(rate(edgesentinel_incident_duration_seconds_sum[1h]))
  / sum(rate(edgesentinel_incident_duration_seconds_count[1h]))
```

## What is not here yet

Time to acknowledge is not exported. The agent never performs the
acknowledgement — the CLI does, in another process — so the agent has nothing
to measure. Exporting it would need either a push gateway or a metric derived
from the table at scrape time, and the table is pruned.

Nothing describes the event history as a metric either: rate of firings by
rule is the one obvious gap, and `edgesentinel_rule_triggered_total` exists in
the code but is never incremented. Use the incident counter instead, or the
database.

Setting the collection up, in either mode, is in
[Set up Prometheus and Grafana](../how-to/set-up-observability.md).
