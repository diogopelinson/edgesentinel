from core.ports import SensorPort
from core.entities import SensorReading


class BaseSensor(SensorPort):
    """
    The base class for every sensor.
    Implements is_available() with a real read attempt —
    if read() does not raise, the sensor is available.
    """

    def __init__(self, sensor_id: str, name: str, unit: str) -> None:
        self.sensor_id = sensor_id
        self.name = name
        self.unit = unit

    def is_available(self) -> bool:
        try:
            self.read()
            return True
        except Exception:
            return False

    def _build_reading(self, value: float) -> SensorReading:
        """A shortcut for assembling a SensorReading from the instance's data."""
        return SensorReading(
            sensor_id=self.sensor_id,
            name=self.name,
            value=round(value, 2),
            unit=self.unit,
        )
