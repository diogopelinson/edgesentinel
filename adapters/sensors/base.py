from core.ports import SensorPort
from core.entities import SensorReading


class BaseSensor(SensorPort):
    """
    Classe base para todos os sensores.
    Implementa is_available() com uma tentativa de leitura real —
    se read() não lançar exceção, o sensor está disponível.
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
        """Atalho para montar um SensorReading com os dados da instância."""
        return SensorReading(
            sensor_id=self.sensor_id,
            name=self.name,
            value=round(value, 2),
            unit=self.unit,
        )