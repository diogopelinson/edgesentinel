# Set up Prometheus and Grafana

Getting the metrics out of the agent and onto a dashboard, in either collection mode.

## Two metric collection modes

**Simple mode — Prometheus scrapes edgesentinel directly**

Best for getting started. In `config.yaml`:

```yaml
exporter:
  port: 8000
  use_otel: false
```

In `infra/docker/prometheus.yml`:

```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: "edgesentinel"
    static_configs:
      - targets:
          - "host.docker.internal:8000"   # Windows/Mac
          # or "172.17.0.1:8000"          # Linux

  - job_name: "ai-service-via-otel"
    static_configs:
      - targets:
          - "edgesentinel-otel-collector:8889"
```

**Advanced mode — via OTel Collector**

To export to Grafana Cloud, Datadog or InfluxDB without changing code. In `config.yaml`:

```yaml
exporter:
  use_otel: true
  backend: otlp
  endpoint: "http://localhost:4317"
  service_name: "edgesentinel"
```

The OTel Collector receives on `:4317` and exposes to Prometheus on `:8889`. The `prometheus.yml` only points to the Collector:

```yaml
scrape_configs:
  - job_name: "edgesentinel"
    static_configs:
      - targets:
          - "edgesentinel-otel-collector:8889"
```

## Checking Prometheus

Open `http://localhost:9090/targets` — all targets should be **UP**.

To confirm metrics are coming in:

```
http://localhost:9090/api/v1/label/__name__/values
```

Should return metric names including `edgesentinel_sensor_value`.

## Setting up Grafana from scratch

**1. Open Grafana**

```
http://localhost:3000
login: admin
password: edgesentinel
```

**2. Add Prometheus as datasource**

1. Side menu → **Connections** → **Data sources**
2. Click **Add data source** → select **Prometheus**
3. URL: `http://prometheus:9090`
4. Click **Save & test**

If you see "Successfully queried the Prometheus API", it's working.

**3. Import the dashboard**

1. Side menu → **Dashboards** → **Import**
2. Click **Upload dashboard JSON file**
3. Select `dashboards/edgesentinel_dashboard_v2.json`
4. Under **Prometheus**, select the datasource from the previous step
5. Click **Import**

The dashboard opens on two rows: **Visão geral**, the current numbers, and
**Incidentes**, which is the one to look at first. It carries open incidents,
open incidents nobody has acknowledged, the P95 duration of the ones that
closed, open incidents by severity over time, which rules are in alarm, and the
rate of openings and closings.

To see it with data and no hardware, run the agent against the `spike`
scenario and leave it for a couple of minutes:

```bash
edgesentinel simulate --scenario spike --interval 1
```

Each spike opens an incident and closes it when the temperature falls back, so
the incident panels fill in with real episodes. Acknowledge one from a second
terminal with `edgesentinel ack <id>` and watch the severity graph move a
series from `triggered` to `acknowledged` on the next scrape — the agent is not
signalled and not restarted.

**4. Useful PromQL queries for building custom panels**

```promql
# current value of all sensors
edgesentinel_sensor_value

# anomaly score by sensor
edgesentinel_anomaly_score{sensor_id="cpu_temp"}

# anomaly rate over last 5 minutes
rate(edgesentinel_anomaly_total[5m])

# pipeline P95 latency
histogram_quantile(0.95, rate(edgesentinel_pipeline_latency_seconds_bucket[5m]))

# AI Service P95 latency in ms
histogram_quantile(0.95, rate(ai_service_inference_latency_ms_milliseconds_bucket[5m]))

# inference rate per second per model
rate(ai_service_inference_total[1m])

# open incidents, zero included -- the gauge is sparse, so the fallback
# is what makes "none open" show as 0 instead of "No data"
sum(edgesentinel_incidents_open) or vector(0)

# open and not acknowledged: the number that asks for action
sum(edgesentinel_incidents_open{state="triggered"}) or vector(0)

# open by severity
sum by (severity) (edgesentinel_incidents_open)

# incidents opened per minute
sum(rate(edgesentinel_incidents_total{transition="opened"}[5m])) * 60

# p95 of incident duration, by severity
histogram_quantile(0.95, sum by (le, severity)
  (rate(edgesentinel_incident_duration_seconds_bucket[30m])))
```

---
