from adapters.actions.base import BaseAction
from core.entities import ActionContext


class GPIOWriteAction(BaseAction):
    """
    Escreve em um pino GPIO quando uma regra dispara.
    Útil para acionar LEDs, relés, buzzers, etc.

    Tenta usar gpiozero (mais portável) e cai para
    RPi.GPIO se necessário.
    """

    def __init__(
        self,
        action_id: str = "gpio_write",
        pin: int = 17,
        value: bool = True,          # True = HIGH, False = LOW
        duration_seconds: float | None = None,  # None = mantém indefinidamente
    ) -> None:
        super().__init__(action_id)
        self.pin = pin
        self.value = value
        self.duration = duration_seconds

    def _run(self, context: ActionContext) -> None:
        try:
            self._write_gpiozero()
        except ImportError:
            self._write_rpigpio()

    def _write_gpiozero(self) -> None:
        import time
        from gpiozero import OutputDevice

        device = OutputDevice(self.pin, active_high=True, initial_value=False)

        if self.value:
            device.on()
        else:
            device.off()

        if self.duration is not None:
            time.sleep(self.duration)
            device.off()

        device.close()

    def _write_rpigpio(self) -> None:
        import time
        import RPi.GPIO as GPIO

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.OUT)
        GPIO.output(self.pin, GPIO.HIGH if self.value else GPIO.LOW)

        if self.duration is not None:
            time.sleep(self.duration)
            GPIO.output(self.pin, GPIO.LOW)

        GPIO.cleanup(self.pin)