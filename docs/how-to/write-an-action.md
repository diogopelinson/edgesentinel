# Write your own action

Implementing ActionPort so a firing rule can do something the project does not ship.

```python
from core.ports import ActionPort
from core.entities import ActionContext
from core.rules import Severity
import requests


ICONS = {
    Severity.INFO:     "ℹ️",
    Severity.WARNING:  "⚠️",
    Severity.CRITICAL: "🚨",
}


class TelegramAction(ActionPort):
    """Sends a Telegram message when a rule fires."""

    def __init__(self, action_id: str, token: str, chat_id: str) -> None:
        self.action_id = action_id
        self._token    = token
        self._chat_id  = chat_id

    def execute(self, context: ActionContext) -> None:
        reading  = context.reading
        score    = context.score
        severity = context.extras.get("severity", Severity.WARNING)

        text = (
            f"{ICONS[severity]} *{context.rule_name}* [{severity.value}]\n"
            f"Sensor: `{reading.sensor_id}`\n"
            f"Value: `{reading.value}{reading.unit}`"
        )

        if score and score.is_anomaly:
            text += f"\nAnomaly score: `{score.score:.2f}`"

        requests.post(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            json={"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
```

The severity of the rule that fired arrives in `context.extras["severity"]` as a `Severity`. For text, use `.value` — on Python 3.10, `str(Severity.CRITICAL)` returns `'Severity.CRITICAL'`, not `'critical'`. The `.get` default covers the action being called outside the `RuleEngine`.

---
