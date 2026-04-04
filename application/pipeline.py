import logging

from core.ports import SensorPort, InferencePort
from application.engine import RuleEngine

logger = logging.getLogger("edgesentinel.pipeline")


class Pipeline:
    """
    Executa o ciclo completo para um sensor:
        1. lê o sensor
        2. roda inferência (se habilitada)
        3. avalia regras e executa ações

    Cada sensor tem seu próprio Pipeline — falha num sensor
    não afeta os outros.
    """

    def __init__(
        self,
        sensor: SensorPort,
        engine: RuleEngine,
        inference: InferencePort | None = None,
    ) -> None:
        self._sensor = sensor
        self._engine = engine
        self._inference = inference

    def run_once(self) -> None:
        """
        Executa um ciclo completo de leitura → inferência → avaliação.
        Captura exceções para não derrubar o MonitorLoop.
        """
        try:
            reading = self._sensor.read()
        except Exception as e:
            logger.error(f"Falha ao ler sensor: {e}")
            return

        score = None
        if self._inference is not None:
            try:
                score = self._inference.predict(reading)
            except Exception as e:
                logger.error(f"Falha na inferência: {e}")

        self._engine.evaluate(reading, score)