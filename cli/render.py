"""
Formatação compartilhada dos comandos de terminal.

Cor por severidade e duração legível aparecem em mais de um comando, e a
escolha precisa ser a mesma nos dois: crítico vermelho num lugar e amarelo no
outro é pior que sem cor nenhuma.
"""

COLORS = {
    "critical": "\033[91m",
    "warning":  "\033[93m",
    "info":     "\033[96m",
}
RESET = "\033[0m"


def human_duration(seconds: float) -> str:
    """
    1830 → '30m'. Escala com a grandeza: segundos para o que acabou de
    acontecer, dias para o incidente que ninguém olhou.

    Duração negativa vira zero — relógio de parede pode andar para trás, e
    'aberto há -3s' não ajuda ninguém.
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
