import argparse
import os
import sys


def _serve(args: argparse.Namespace) -> None:
    from host import serve

    serve(host=args.host, port=args.port, tunnel=args.tunnel and not args.no_tunnel)


def _scheduler(_args: argparse.Namespace) -> None:
    from scheduler import run

    run()


def _doctor(_args: argparse.Namespace) -> None:
    from host import doctor

    raise SystemExit(doctor())


def _setup(args: argparse.Namespace) -> None:
    from host import setup

    raise SystemExit(
        setup(
            token=args.token,
            skip_helper=args.skip_helper,
            skip_image=args.skip_image,
            skip_env=args.skip_env,
            skip_postgres=args.skip_postgres,
            env_file=args.env_file,
        )
    )


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
    if argv[:1] == ["scheduler"]:
        _hidden("scheduler", _scheduler, argv[1:])
        return
    if argv[:1] == ["init-host"]:
        _hidden("init-host", _init_host, argv[1:])
        return

    parser = argparse.ArgumentParser(prog="opengpu", description="OpenGPU host runtime")
    commands = parser.add_subparsers(dest="command", required=True, metavar="{serve,setup,doctor,migrate,admin}")

    serve = commands.add_parser("serve", help="Run the API, scheduler, and local SSH gateway")
    serve.add_argument("--host", default=os.environ.get("API_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("API_PORT", "8000")))
    serve.add_argument("--tunnel", action="store_true", help="Start a remote SSH tunnel (optional; requires a token)")
    serve.add_argument("--no-tunnel", action="store_true", help=argparse.SUPPRESS)
    serve.set_defaults(func=_serve)

    setup = commands.add_parser("setup", help="Write .env, install the storage helper, and pull the GPU image")
    setup.add_argument("--token", help="Remote SSH tunnel authtoken (stored in .env, not printed)")
    setup.add_argument("--skip-helper", action="store_true", help="Do not install the storage helper")
    setup.add_argument("--skip-image", action="store_true", help="Do not pull DOCKER_IMAGE")
    setup.add_argument("--skip-env", action="store_true", help="Do not prompt for or rewrite the environment file")
    setup.add_argument("--skip-postgres", action="store_true", help="Do not start PostgreSQL with Docker Compose")
    setup.add_argument("--env-file", help="Path to write (default: .env, or ~/.config/opengpu/env when installed)")
    setup.set_defaults(func=_setup)

    doctor = commands.add_parser("doctor", help="Check that this host can run OpenGPU")
    doctor.set_defaults(func=_doctor)

    migrate_cmd = commands.add_parser("migrate", help="Apply the PostgreSQL schema or pending migrations")
    migrate_cmd.set_defaults(func=_migrate)

    commands.add_parser("admin", help="Administration commands")
    args = parser.parse_args(argv)
    args.func(args)


def _hidden(name: str, func, argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog=f"opengpu {name}")
    args = parser.parse_args(argv)
    func(args)


if __name__ == "__main__":
    main()
