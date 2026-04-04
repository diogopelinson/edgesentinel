import json
import urllib.request
import urllib.error
from adapters.actions.base import BaseAction
from core.entities import ActionContext


class WebhookAction(BaseAction):
    """
    Faz um POST HTTP com os dados da leitura em JSON.
    Usa urllib da stdlib — sem dependência de requests ou httpx.
    Compatível com Slack, Discord, PagerDuty, n8n, etc.
    """

    def __init__(
        self,
        action_id: str = "webhook",
        url: str = "",
        timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(action_id)
        self.url = url
        self.timeout = timeout_seconds

    def _run(self, context: ActionContext) -> None:
        if not self.url:
            raise ValueError("WebhookAction configurado sem URL.")

        payload = self._build_payload(context)
        self._post(payload)

    def _build_payload(self, context: ActionContext) -> dict:
        reading = context.reading
        payload = {
            "rule": context.rule_name,
            "sensor_id": reading.sensor_id,
            "sensor_name": reading.name,
            "value": reading.value,
            "unit": reading.unit,
            "timestamp": reading.timestamp,
        }

        if context.score is not None:
            payload["anomaly"] = {
                "score": context.score.score,
                "threshold": context.score.threshold,
                "model_id": context.score.model_id,
            }

        return payload

    def _post(self, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url=self.url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Webhook retornou status {resp.status}")