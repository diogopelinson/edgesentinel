import sys
import logging
import argparse
from pathlib import Path

from cli import __version__
from config.loader import load
from cli.builder import build_monitor


def main() -> None:
    args = _parse_args()
    _setup_logging(args.log_level)

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "simulate":
        _cmd_simulate(args)
    elif args.command == "doctor":
        _cmd_doctor(args)
    elif args.command == "events":
        _cmd_events(args)
    elif args.command == "incidents":
        _cmd_incidents(args)
    elif args.command in ("ack", "resolve"):
        _cmd_transition(args)


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


def _cmd_doctor(args) -> None:
    from cli.doctor import run_doctor
    run_doctor(config_path=str(args.config))


def _cmd_events(args) -> None:
    from cli.events import run_events
    sys.exit(run_events(
        config_path=args.config,
        severity=args.severity,
        sensor=args.sensor,
        rule=args.rule,
        window_seconds=args.last,
        limit=args.limit,
        as_json=args.json,
    ))


def _cmd_incidents(args) -> None:
    from cli.incidents import run_incidents
    sys.exit(run_incidents(
        config_path=args.config,
        include_resolved=args.all,
        severity=args.severity,
        rule=args.rule,
        window_seconds=args.last,
        limit=args.limit,
        as_json=args.json,
    ))


def _cmd_transition(args) -> None:
    """ack e resolve diferem só no destino — o resto é o mesmo caminho."""
    from cli.incidents import run_ack, run_resolve
    comando = run_ack if args.command == "ack" else run_resolve
    sys.exit(comando(config_path=args.config, incident_id=args.incident_id))


def _duration_arg(text: str) -> float:
    """--last validado no parse: erro de argumento, não exceção no meio da execução."""
    from cli.events import parse_duration
    try:
        return parse_duration(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"precisa ser um inteiro: '{text}'") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"precisa ser maior que zero: {value}")
    return value


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

    # --- subcomando: doctor ---
    doc_p = sub.add_parser("doctor", help="Inspeciona o ambiente e reporta problemas")
    doc_p.add_argument("--config", "-c", type=Path, default=Path("config.yaml"))
    doc_p.add_argument("--log-level", "-l", choices=["DEBUG","INFO","WARNING","ERROR"], default="WARNING")

    # --- subcomando: events ---
    ev_p = sub.add_parser("events", help="Lista o histórico de regras disparadas")
    ev_p.add_argument("--config", "-c", type=Path, default=Path("config.yaml"))
    ev_p.add_argument(
        "--severity", "-s",
        type=str.lower,
        choices=["info", "warning", "critical"],
        help="Só eventos desse nível",
    )
    ev_p.add_argument("--sensor", help="Só eventos desse sensor_id")
    ev_p.add_argument("--rule", "-r", help="Só eventos dessa regra")
    ev_p.add_argument(
        "--last",
        type=_duration_arg,
        metavar="DURAÇÃO",
        help="Janela até agora: 30m, 24h, 7d",
    )
    ev_p.add_argument(
        "--limit", "-n",
        type=_positive_int,
        default=20,
        help="Máximo de eventos, mais recentes primeiro (padrão: 20)",
    )
    ev_p.add_argument("--json", action="store_true", help="Uma linha JSON por evento")
    ev_p.add_argument("--log-level", "-l", choices=["DEBUG","INFO","WARNING","ERROR"], default="WARNING")

    # --- subcomando: incidents ---
    inc_p = sub.add_parser("incidents", help="Lista incidentes abertos")
    inc_p.add_argument("--config", "-c", type=Path, default=Path("config.yaml"))
    inc_p.add_argument(
        "--all", "-a",
        action="store_true",
        help="Inclui os já resolvidos (o padrão mostra só os abertos)",
    )
    inc_p.add_argument(
        "--severity", "-s",
        type=str.lower,
        choices=["info", "warning", "critical"],
        help="Só incidentes desse nível",
    )
    inc_p.add_argument("--rule", "-r", help="Só incidentes dessa regra")
    inc_p.add_argument(
        "--last",
        type=_duration_arg,
        metavar="DURAÇÃO",
        help="Abertos nesta janela até agora: 30m, 24h, 7d",
    )
    inc_p.add_argument(
        "--limit", "-n",
        type=_positive_int,
        default=20,
        help="Máximo de incidentes, mais recentes primeiro (padrão: 20)",
    )
    inc_p.add_argument("--json", action="store_true", help="Uma linha JSON por incidente")
    inc_p.add_argument("--log-level", "-l", choices=["DEBUG","INFO","WARNING","ERROR"], default="WARNING")

    # --- subcomandos: ack e resolve ---
    for nome, ajuda in (
        ("ack",     "Reconhece um incidente: para de repetir as ações, segue registrando"),
        ("resolve", "Fecha um incidente à mão, sem esperar a leitura recuar"),
    ):
        p = sub.add_parser(nome, help=ajuda)
        p.add_argument("incident_id", type=_positive_int, metavar="ID", help="Id do incidente")
        p.add_argument("--config", "-c", type=Path, default=Path("config.yaml"))
        p.add_argument("--log-level", "-l", choices=["DEBUG","INFO","WARNING","ERROR"], default="WARNING")

    return parser.parse_args()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


if __name__ == "__main__":
    main()
