# Write your own sensor

Implementing SensorPort for a device the project does not ship.

```python
from core.ports import SensorPort
from core.entities import SensorReading


class MotorTemperatureSensor(SensorPort):
    """Reads motor temperature from a device file."""

    def __init__(self, sensor_id: str, device_path: str) -> None:
        self.sensor_id   = sensor_id
        self.device_path = device_path

    def read(self) -> SensorReading:
        with open(self.device_path) as f:
            value = float(f.read().strip()) / 1000.0

        return SensorReading(
            sensor_id=self.sensor_id,
            name="Motor Temperature",
            value=value,
            unit="°C",
        )

    def is_available(self) -> bool:
        import os
        return os.path.exists(self.device_path)
```

## Availability contract

Every sensor follows three rules, and the example above already meets all of them:

1. **`__init__` does not touch the hardware** — it only stores configuration. No opening files, probing devices or running commands in the constructor.
2. **Absence is reported through `is_available()`**, never by raising. At startup, `edgesentinel run` skips unavailable sensors with a `WARNING` and carries on with the rest; `edgesentinel doctor` lists them as unavailable. A constructor that raises sends both down their error path instead.
3. **When `read()` fails, the message says where it looked.** `"No source found. Paths tried: /sys/..., /usr/bin/..."` turns a diagnosis into a lookup.

Inheriting from `adapters.sensors.base.BaseSensor` instead of `SensorPort` gives you `is_available()` for free: it attempts a `read()` and returns `False` if the read raises.

## Registering it

Add the class to `_REGISTRY` in `adapters/sensors/registry.py`, keyed by the `type` you want to write in the YAML:

```python
_REGISTRY: dict[str, type[BaseSensor]] = {
    "cpu_temperature":    CpuTemperatureSensor,
    "cpu_usage":          CpuUsageSensor,
    "memory_usage":       MemoryUsageSensor,
    "uptime":             UptimeSensor,
    "load_average":       LoadAverageSensor,
    "motor_temperature":  MotorTemperatureSensor,
}
```

## Configuring it

Everything after `sensor_id` in your constructor comes from the `params` block:

```yaml
sensors:
  - id: motor_esquerdo
    type: motor_temperature
    params:
      device_path: /dev/motor0
```

**Your constructor signature is the config schema.** There is no second place
to declare what the sensor accepts, and nothing to keep in sync — a param no
parameter matches fails at startup with a message naming the sensor, the
offending params and the accepted ones. Give every param a default that works,
and a YAML entry with just `id` and `type` will keep working.

The check happens before your constructor runs, so a sensor that claims a pin
or opens a bus has not done it yet when the config is wrong. If your sensor
genuinely takes arbitrary keys — a generic I2C or SPI adapter — declare
`**kwargs` and the check lets everything through.

`sensor_id` is the one name you cannot take from `params`: it comes from the
`id:` field, and asking for it there is refused rather than silently shadowing
the sensor's own id.

---
