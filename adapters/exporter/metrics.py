from prometheus_client import Gauge, Counter, Histogram

# --- Sensor metrics ---

SENSOR_VALUE = Gauge(
    name="edgesentinel_sensor_value",
    documentation="Valor atual lido do sensor",
    labelnames=["sensor_id", "sensor_name", "unit"],
)

# --- Anomaly metrics ---

ANOMALY_SCORE = Gauge(
    name="edgesentinel_anomaly_score",
    documentation="Score de anomalia retornado pelo modelo (0.0 a 1.0)",
    labelnames=["sensor_id", "model_id"],
)

ANOMALY_TOTAL = Counter(
    name="edgesentinel_anomaly_total",
    documentation="Total de anomalias detectadas desde o início",
    labelnames=["sensor_id", "model_id"],
)

# --- Rule metrics ---

RULE_TRIGGERED_TOTAL = Counter(
    name="edgesentinel_rule_triggered_total",
    documentation="Total de vezes que cada regra foi disparada",
    labelnames=["rule_name"],
)

# --- Incident metrics ---

# The open-incidents gauge is not here: it is read from the store on every
# scrape, by OpenIncidentsCollector. These two are per-process because a
# counter and a histogram have to be monotonic, and the table does not
# guarantee that — prune() deletes a resolved incident once retention is up.

INCIDENTS_TOTAL = Counter(
    name="edgesentinel_incidents_total",
    documentation="Transições do ciclo de incidente feitas por este agente",
    labelnames=["rule", "severity", "transition"],
)

INCIDENT_DURATION = Histogram(
    name="edgesentinel_incident_duration_seconds",
    documentation="Quanto durou cada incidente fechado, em segundos",
    labelnames=["severity"],
    # from seconds to a day: a CPU spike closes in seconds, a full disk that
    # nobody saw lasts the whole weekend. A linear scale would throw both
    # extremes into the same bucket
    buckets=[5.0, 15.0, 60.0, 300.0, 900.0, 3_600.0, 21_600.0, 86_400.0],
)

# --- Performance metrics ---

INFERENCE_LATENCY = Histogram(
    name="edgesentinel_inference_latency_seconds",
    documentation="Tempo de execução da inferência em segundos",
    labelnames=["model_id"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

PIPELINE_LATENCY = Histogram(
    name="edgesentinel_pipeline_latency_seconds",
    documentation="Tempo total do ciclo sense → infer → act",
    labelnames=["sensor_id"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
