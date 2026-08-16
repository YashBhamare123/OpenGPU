import argparse
import os
import sys


def _serve(args: argparse.Namespace) -> None:
    from host import serve

    serve(host=args.host, port=args.port, tunnel=not args.no_tunnel)


def _scheduler(_args: argparse.Namespace) -> None:
    from scheduler import run

    run()


def _doctor(_args: argparse.Namespace) -> None:
    from host import doctor

    raise SystemExit(doctor())


def _setup(args: argparse.Namespace) -> None:
    from host import setup

    raise SystemExit(setup(token=args.token, skip_helper=args.skip_helper, skip_image=args.skip_image))


def _migrate(_args: argparse.Namespace) -> None:
    from migrate import migrate

    raise SystemExit(migrate())


def _init_host(_args: argparse.Namespace) -> None:
    from host import setup

    raise SystemExit(setup())


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["admin"]:
        from admin import parser as admin_parser

        admin_args = admin_parser().parse_args(argv[1:])
        admin_args.func(admin_args)
        return

    parser = argparse.ArgumentParser(prog="opengpu", description="OpenGPU host runtime")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Run the API, scheduler, SSH gateway, and optional remote tunnel")
    serve.add_argument("--host", default=os.environ.get("API_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("API_PORT", "8000")))
    serve.add_argument("--no-tunnel", action="store_true", help="Do not start the remote SSH tunnel")
    serve.set_defaults(func=_serve)

    setup = commands.add_parser("setup", help="Install the storage helper and optional remote-access token")
    setup.add_argument("--token", help="Remote SSH tunnel authtoken (stored in .env, not printed)")
    setup.add_argument("--skip-helper", action="store_true", help="Only store the tunnel token")
    setup.add_argument("--skip-image", action="store_true", help="Do not pull DOCKER_IMAGE")
    setup.set_defaults(func=_setup)

    doctor = commands.add_parser("doctor", help="Check that this host can run OpenGPU")
    doctor.set_defaults(func=_doctor)

    migrate_cmd = commands.add_parser("migrate", help="Apply the PostgreSQL schema or pending migrations")
    migrate_cmd.set_defaults(func=_migrate)

    scheduler = commands.add_parser("scheduler", help=argparse.SUPPRESS)
    scheduler.set_defaults(func=_scheduler)
    init_host = commands.add_parser("init-host", help=argparse.SUPPRESS)
    init_host.set_defaults(func=_init_host)
    commands.add_parser("admin", help="Administration commands")
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
