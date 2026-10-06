"""
Formatting shared by the terminal commands.

Color by severity and a readable duration appear in more than one command, and
the choice has to match across them: critical in red in one place and amber in
another is worse than no color at all.
"""

COLORS = {
    "critical": "\033[91m",
    "warning":  "\033[93m",
    "info":     "\033[96m",
}
RESET = "\033[0m"


def human_duration(seconds: float) -> str:
    """
    1830 → '30m'. Scales with the magnitude: seconds for what just happened,
    days for the incident nobody looked at.

    A negative duration becomes zero — a wall clock can step backwards, and
    "open for -3s" helps nobody.
    """
    total = int(max(0.0, seconds))
    if total < 60:
        return f"{total}s"

    minutos, _ = divmod(total, 60)
    if minutos < 60:
        return f"{minutos}m"

    horas, minutos = divmod(minutos, 60)
    if horas < 24:
        return f"{horas}h" if minutos == 0 else f"{horas}h {minutos}m"

    dias, horas = divmod(horas, 24)
    return f"{dias}d" if horas == 0 else f"{dias}d {horas}h"
