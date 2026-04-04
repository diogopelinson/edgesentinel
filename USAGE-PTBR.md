# Usando o edgesentinel como biblioteca

O `edgesentinel` pode ser usado de duas formas: via CLI (`edgesentinel run`) ou importado diretamente no seu código Python como uma biblioteca. Esse guia cobre a segunda forma.

---

## Instalação

```bash
pip install edgesentinel[onnx]
```

---

## Caso 1 — Uso mais simples: carregar do config.yaml

Se você já tem um `config.yaml`, pode montar e iniciar o sistema com poucas linhas:

```python
from config.loader import load
from cli.builder import build_monitor

# carrega o config.yaml e monta o sistema completo
config  = load("config.yaml")
monitor = build_monitor(config)

# inicia o loop de monitoramento (bloqueante)
monitor.start()
```

Isso é equivalente a rodar `edgesentinel run --config config.yaml`.

---

## Caso 2 — Controle total: montando as peças manualmente

Se você quiser mais controle — sensores customizados, lógica de regras dinâmica, integração com seu próprio sistema — pode montar cada peça separadamente.

### Passo 1: criar sensores

```python
from adapters.sensors.cpu_temp import CpuTemperatureSensor
from adapters.sensors.memory_usage import MemoryUsageSensor
from adapters.sensors.simulated import SimulatedSensor

# sensores reais (precisam de Linux)
cpu_sensor = CpuTemperatureSensor(sensor_id="cpu_temp")
mem_sensor = MemoryUsageSensor(sensor_id="memory_usage")

# sensor simulado (funciona em qualquer OS — útil para testes)
sim_sensor = SimulatedSensor(
    sensor_id="cpu_temp",
    name="CPU Temperature",
    unit="°C",
    base_value=58.0,
    amplitude=5.0,
    scenario="stress",   # normal | stress | spike
)
```

### Passo 2: criar o backend de inferência

```python
from adapters.inference.dummy import DummyInferenceAdapter
from adapters.inference.onnx import ONNXInferenceAdapter

# dummy — sempre retorna score 0.0, útil para desenvolvimento
inference = DummyInferenceAdapter()

# ONNX — modelo real treinado com scripts/train_model.py
inference = ONNXInferenceAdapter(threshold=0.7)
inference.load("models/anomaly.onnx")
```

### Passo 3: criar ações

```python
from adapters.actions.log import LogAction
from adapters.actions.webhook import WebhookAction

log_action     = LogAction(action_id="log", level="WARNING")
webhook_action = WebhookAction(
    action_id="webhook",
    url="https://hooks.exemplo.com/alerta",
    timeout_seconds=5.0,
)

actions = {
    "log":     log_action,
    "webhook": webhook_action,
}
```

### Passo 4: criar regras

```python
from core.rules import Rule, Condition

rules = [
    Rule(
        name="alta_temperatura",
        condition=Condition(
            sensor_id="cpu_temp",
            operator=">",       # > < >= <= == anomaly
            threshold=75.0,
        ),
        action_ids=["log", "webhook"],
        cooldown_seconds=60.0,
    ),
    Rule(
        name="anomalia_ml",
        condition=Condition(
            sensor_id="cpu_temp",
            operator="anomaly",   # usa o score do modelo
        ),
        action_ids=["log"],
        cooldown_seconds=30.0,
    ),
]
```

### Passo 5: montar o engine e o pipeline

```python
from application.engine import RuleEngine
from application.pipeline import Pipeline
from adapters.exporter.prometheus import PrometheusExporter

# exporter opcional — expõe /metrics na porta 8000
exporter = PrometheusExporter(port=8000)
exporter.start()

engine = RuleEngine(rules=rules, actions=actions)

pipeline = Pipeline(
    sensor=cpu_sensor,
    engine=engine,
    inference=inference,
    exporter=exporter,    # opcional
)
```

### Passo 6: rodar

```python
import time

while True:
    pipeline.run_once()
    time.sleep(5)
```

Ou com o `MonitorLoop` para loop assíncrono com shutdown gracioso:

```python
from application.monitor import MonitorLoop

monitor = MonitorLoop(
    pipelines=[pipeline],
    poll_interval_seconds=5.0,
    exporter=exporter,
)

monitor.start()   # bloqueante — Ctrl+C encerra limpo
```

---

## Caso 3 — Criando seu próprio sensor

Implemente `SensorPort` de `core/ports.py`:

```python
from core.ports import SensorPort
from core.entities import SensorReading
import time


class MeuSensorCustom(SensorPort):
    """
    Sensor que lê de qualquer fonte — arquivo, serial, I2C, API, etc.
    """

    def __init__(self, sensor_id: str) -> None:
        self.sensor_id = sensor_id

    def read(self) -> SensorReading:
        # sua lógica de leitura aqui
        valor = self._ler_hardware()

        return SensorReading(
            sensor_id=self.sensor_id,
            name="Meu Sensor",
            value=valor,
            unit="°C",
        )

    def is_available(self) -> bool:
        try:
            self.read()
            return True
        except Exception:
            return False

    def _ler_hardware(self) -> float:
        # exemplo: lê de um arquivo, porta serial, I2C, etc.
        return 42.0
```

Plugar no sistema:

```python
meu_sensor = MeuSensorCustom(sensor_id="meu_sensor")

pipeline = Pipeline(
    sensor=meu_sensor,
    engine=engine,
    inference=inference,
)
```

---

## Caso 4 — Criando sua própria ação

Implemente `ActionPort` de `core/ports.py`:

```python
from core.ports import ActionPort
from core.entities import ActionContext
import requests   # exemplo com requests


class SlackAction(ActionPort):
    """Envia mensagem formatada para um canal do Slack."""

    def __init__(self, action_id: str, webhook_url: str) -> None:
        self.action_id = action_id
        self.webhook_url = webhook_url

    def execute(self, context: ActionContext) -> None:
        reading = context.reading
        score   = context.score

        texto = (
            f":warning: *{context.rule_name}*\n"
            f"Sensor: `{reading.sensor_id}` — "
            f"Valor: `{reading.value}{reading.unit}`"
        )

        if score is not None and score.is_anomaly:
            texto += f"\nAnomaly score: `{score.score:.2f}`"

        requests.post(self.webhook_url, json={"text": texto}, timeout=5)
```

---

## Caso 5 — Lendo um sensor manualmente (sem pipeline)

Se você só quer ler um sensor e usar o valor no seu código:

```python
from adapters.sensors.cpu_temp import CpuTemperatureSensor

sensor  = CpuTemperatureSensor(sensor_id="cpu_temp")

if sensor.is_available():
    reading = sensor.read()
    print(f"{reading.name}: {reading.value}{reading.unit}")
    # CPU Temperature: 62.5°C
```

---

## Caso 6 — Rodando inferência manualmente

Se você só quer usar o modelo de anomalia no seu código:

```python
from adapters.inference.onnx import ONNXInferenceAdapter
from core.entities import SensorReading

adapter = ONNXInferenceAdapter(threshold=0.7)
adapter.load("models/anomaly.onnx")

reading = SensorReading(
    sensor_id="cpu_temp",
    name="CPU Temperature",
    value=85.0,
    unit="°C",
)

score = adapter.predict(reading)

print(f"Score: {score.score:.3f}")
print(f"É anomalia: {score.is_anomaly}")
# Score: 0.937
# É anomalia: True
```

---

## Referência das interfaces principais

### `SensorPort`

```python
class SensorPort(ABC):
    def read(self) -> SensorReading: ...       # lê uma medição
    def is_available(self) -> bool: ...        # verifica se o sensor existe
```

### `InferencePort`

```python
class InferencePort(ABC):
    def predict(self, reading: SensorReading) -> AnomalyScore: ...
    def load(self, model_path: str) -> None: ...
```

### `ActionPort`

```python
class ActionPort(ABC):
    def execute(self, context: ActionContext) -> None: ...
```

### `SensorReading`

```python
@dataclass(frozen=True)
class SensorReading:
    sensor_id: str
    name: str
    value: float
    unit: str
    timestamp: float      # auto-gerado
    metadata: dict        # campos extras opcionais
```

### `AnomalyScore`

```python
@dataclass(frozen=True)
class AnomalyScore:
    score: float          # 0.0 = normal, 1.0 = anomalia total
    threshold: float      # limiar configurado
    is_anomaly: bool      # score >= threshold
    model_id: str
    reading: SensorReading
```

### `ActionContext`

```python
@dataclass
class ActionContext:
    rule_name: str
    reading: SensorReading
    score: AnomalyScore | None    # None se inferência não estiver ativa
    extras: dict                   # dados adicionais opcionais
```

### `Rule`

```python
@dataclass
class Rule:
    name: str
    condition: Condition
    action_ids: list[str]
    enabled: bool = True
    cooldown_seconds: float = 0.0
```

### `Condition`

```python
@dataclass
class Condition:
    sensor_id: str
    operator: str        # ">" | "<" | ">=" | "<=" | "==" | "anomaly"
    threshold: float = 0.0
```

---

## Exemplo completo

Script autossuficiente que roda o sistema completo programaticamente:

```python
import time
from adapters.sensors.simulated import SimulatedSensor
from adapters.inference.onnx import ONNXInferenceAdapter
from adapters.actions.log import LogAction
from adapters.actions.webhook import WebhookAction
from adapters.exporter.prometheus import PrometheusExporter
from application.engine import RuleEngine
from application.pipeline import Pipeline
from application.monitor import MonitorLoop
from core.rules import Rule, Condition


def main():
    # sensores
    sensors = [
        SimulatedSensor("cpu_temp",  "CPU Temperature", "°C", base_value=60.0, scenario="stress"),
        SimulatedSensor("cpu_usage", "CPU Usage",       "%",  base_value=70.0, scenario="stress"),
    ]

    # inferência
    inference = ONNXInferenceAdapter(threshold=0.7)
    inference.load("models/anomaly.onnx")

    # ações
    actions = {
        "log":     LogAction(action_id="log"),
        "webhook": WebhookAction(action_id="webhook", url="https://webhook.site/sua-url"),
    }

    # regras
    rules = [
        Rule(
            name="alta_temperatura",
            condition=Condition(sensor_id="cpu_temp", operator=">", threshold=75.0),
            action_ids=["log", "webhook"],
            cooldown_seconds=60.0,
        ),
    ]

    # monta e inicia
    exporter = PrometheusExporter(port=8000)
    engine   = RuleEngine(rules=rules, actions=actions)
    pipelines = [
        Pipeline(sensor=s, engine=engine, inference=inference, exporter=exporter)
        for s in sensors
    ]

    monitor = MonitorLoop(pipelines=pipelines, poll_interval_seconds=2.0, exporter=exporter)
    monitor.start()


if __name__ == "__main__":
    main()
```