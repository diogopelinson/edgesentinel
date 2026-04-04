import sys
import logging
import argparse
from pathlib import Path

__version__ = "0.1.0"
from config.loader import load
from cli.builder import build_monitor


def main() -> None:
    args = _parse_args()
    _setup_logging(args.log_level)

    logger = logging.getLogger("edgesentinel")
    logger.info(f"edgesentinel v{__version__} iniciando...")

    try:
        config  = load(args.config)
        monitor = build_monitor(config)
        monitor.start()
    except FileNotFoundError as e:
        print(f"\nErro: {e}", file=sys.stderr)
        print("Verifique o caminho do arquivo de configuração.", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"\nErro de configuração: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"\nErro ao iniciar: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass    # SIGINT tratado pelo MonitorLoop — só sai limpo


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="edgesentinel",
        description="Observabilidade inteligente para dispositivos Linux embarcados.",
    )

    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=Path("config.yaml"),
        metavar="PATH",
        help="Caminho para o arquivo de configuração (padrão: config.yaml)",
    )

    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        metavar="LEVEL",
        help="Nível de log (padrão: INFO)",
    )

    return parser.parse_args()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )