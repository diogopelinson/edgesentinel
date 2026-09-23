import logging
import pytest

from adapters.actions.log import LogAction
from core.entities import ActionContext, SensorReading
from core.rules import Severity


@pytest.fixture
def context(cpu_reading) -> ActionContext:
    return ActionContext(
        rule_name="alta_temperatura",
        reading=cpu_reading,
    )


@pytest.fixture
def context_with_score(cpu_reading, anomaly_score) -> ActionContext:
    return ActionContext(
        rule_name="anomalia_detectada",
        reading=cpu_reading,
        score=anomaly_score,
    )


class TestLogAction:

    def test_logs_rule_name(self, context, caplog):
        """caplog é fixture nativa do pytest — captura logs emitidos durante o teste."""
        action = LogAction()

        with caplog.at_level(logging.WARNING, logger="edgesentinel.action.log"):
            action.execute(context)

        assert "alta_temperatura" in caplog.text

    def test_logs_sensor_id(self, context, caplog):
        action = LogAction()

        with caplog.at_level(logging.WARNING, logger="edgesentinel.action.log"):
            action.execute(context)

        assert "cpu_temp" in caplog.text

    def test_logs_sensor_value(self, context, caplog):
        action = LogAction()

        with caplog.at_level(logging.WARNING, logger="edgesentinel.action.log"):
            action.execute(context)

        assert "72.5" in caplog.text

    def test_logs_anomaly_score_when_present(self, context_with_score, caplog):
        action = LogAction()

        with caplog.at_level(logging.WARNING, logger="edgesentinel.action.log"):
            action.execute(context_with_score)

        assert "anomaly_score" in caplog.text
        assert "0.91" in caplog.text

    def test_no_anomaly_info_when_score_absent(self, context, caplog):
        action = LogAction()

        with caplog.at_level(logging.WARNING, logger="edgesentinel.action.log"):
            action.execute(context)

        assert "anomaly_score" not in caplog.text

    def test_respects_log_level(self, context, caplog):
        """LogAction com nível ERROR não deve aparecer em captura WARNING."""
        action = LogAction(level="ERROR")

        with caplog.at_level(logging.WARNING, logger="edgesentinel.action.log"):
            action.execute(context)

        # a mensagem existe mas com nível ERROR
        assert any(r.levelno == logging.ERROR for r in caplog.records)

    def test_invalid_level_defaults_to_warning(self, context, caplog):
        """Nível inválido no config deve usar WARNING como fallback."""
        action = LogAction(level="INVALIDO")

        with caplog.at_level(logging.WARNING, logger="edgesentinel.action.log"):
            action.execute(context)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING

    def test_severity_in_context_overrides_the_configured_level(self, context, caplog):
        """
        O nível do construtor é o default da ação; a severidade da regra que
        disparou é mais específica e deve vencer.
        """
        context.extras["severity"] = Severity.CRITICAL
        action = LogAction(level="WARNING")

        with caplog.at_level(logging.INFO, logger="edgesentinel.action.log"):
            action.execute(context)

        assert caplog.records[0].levelno == logging.CRITICAL

    def test_info_severity_logs_at_info_level(self, context, caplog):
        context.extras["severity"] = Severity.INFO
        action = LogAction()

        with caplog.at_level(logging.INFO, logger="edgesentinel.action.log"):
            action.execute(context)

        assert caplog.records[0].levelno == logging.INFO

    def test_falls_back_to_configured_level_without_severity(self, context, caplog):
        """Contexto sem severidade preserva o comportamento atual."""
        action = LogAction(level="ERROR")

        with caplog.at_level(logging.INFO, logger="edgesentinel.action.log"):
            action.execute(context)

        assert caplog.records[0].levelno == logging.ERROR

    def test_execute_does_not_raise_on_empty_context(self):
        """BaseAction captura exceções — LogAction nunca deve propagar erros."""
        reading = SensorReading(
            sensor_id="cpu_temp",
            name="CPU Temperature",
            value=72.5,
            unit="°C",
        )
        context = ActionContext(rule_name="teste", reading=reading)
        action = LogAction()

        action.execute(context)
