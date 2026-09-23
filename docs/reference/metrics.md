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

Two of those repay attention. `edgesentinel_pipeline_latency_seconds` includes
the actions, so a slow webhook shows up here rather than anywhere else — this
is how you notice that an alert path is dragging the loop. And
`edgesentinel_anomaly_score` is a gauge over the raw score, not over the
rule's verdict: it moves even while nothing is firing, which is what makes a
threshold easy to choose from the graph.

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
```

## What is not here yet

There are no incident metrics: open incidents by severity, by rule, and time
to acknowledge are not exported. Until `incident-metrics` lands
([roadmap](../roadmap.json)), incident state is visible in the database and in
the logs, not on a dashboard.

Setting the collection up, in either mode, is in
[Set up Prometheus and Grafana](../how-to/set-up-observability.md).
