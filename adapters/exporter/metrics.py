from prometheus_client import Gauge, Counter, Histogram

# --- Métricas de sensor ---

SENSOR_VALUE = Gauge(
    name="edgesentinel_sensor_value",
    documentation="Valor atual lido do sensor",
    labelnames=["sensor_id", "sensor_name", "unit"],
)

# --- Métricas de anomalia ---

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

# --- Métricas de regras ---

RULE_TRIGGERED_TOTAL = Counter(
    name="edgesentinel_rule_triggered_total",
    documentation="Total de vezes que cada regra foi disparada",
    labelnames=["rule_name"],
)

# --- Métricas de performance ---

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