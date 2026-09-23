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

---
