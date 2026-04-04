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

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "simulate":
        _cmd_simulate(args)


def _cmd_run(args) -> None:
    logger = logging.getLogger("edgesentinel")
    logger.info(f"edgesentinel v{__version__} iniciando...")
    try:
        config  = load(args.config)
        monitor = build_monitor(config)
        monitor.start()
    except FileNotFoundError as e:
        print(f"\nErro: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"\nErro de configuração: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


def _cmd_simulate(args) -> None:
    from cli.simulate import run_simulate
    run_simulate(
        scenario=args.scenario,
        config_path=args.config,
        interval=args.interval,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="edgesentinel",
        description="Observabilidade inteligente para dispositivos Linux embarcados.",
    )
    parser.add_argument("--version", "-v", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    # --- subcomando: run ---
    run_p = sub.add_parser("run", help="Inicia o monitoramento com hardware real")
    run_p.add_argument("--config", "-c", type=Path, default=Path("config.yaml"))
    run_p.add_argument("--log-level", "-l", choices=["DEBUG","INFO","WARNING","ERROR"], default="INFO")

    # --- subcomando: simulate ---
    sim_p = sub.add_parser("simulate", help="Simula sensores sem hardware real")
    sim_p.add_argument(
        "--scenario", "-s",
        choices=["normal", "stress", "spike"],
        default="normal",
        help="Cenário de simulação (padrão: normal)",
    )
    sim_p.add_argument("--config", "-c", type=Path, default=Path("config.yaml"))
    sim_p.add_argument("--interval", "-i", type=float, default=2.0, help="Intervalo entre leituras em segundos")
    sim_p.add_argument("--log-level", "-l", choices=["DEBUG","INFO","WARNING","ERROR"], default="INFO")

    return parser.parse_args()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )