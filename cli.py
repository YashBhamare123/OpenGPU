import argparse
import os
import sys
from datetime import datetime, timedelta, timezone


def _serve(args: argparse.Namespace) -> None:
    from host import serve

    serve(host=args.host, port=args.port, tunnel=args.tunnel and not args.no_tunnel)


def _scheduler(_args: argparse.Namespace) -> None:
    from scheduler import run

    run()


def _doctor(args: argparse.Namespace) -> None:
    from host import doctor

    raise SystemExit(doctor(cpu=args.cpu))


def _setup(args: argparse.Namespace) -> None:
    from host import setup

    raise SystemExit(
        setup(
            token=args.token,
            skip_helper=args.skip_helper,
            skip_image=args.skip_image,
            skip_env=args.skip_env,
            skip_postgres=args.skip_postgres,
            cpu=args.cpu,
            env_file=args.env_file,
        )
    )


def _migrate(_args: argparse.Namespace) -> None:
    from migrate import migrate

    raise SystemExit(migrate())


def _init_host(_args: argparse.Namespace) -> None:
    from host import setup

    raise SystemExit(setup())


def _share(args: argparse.Namespace) -> None:
    from share import create_claim
    from ui import panel, print_banner

    print_banner()
    result = create_claim(args.handle, hours=args.hours)
    print(
        panel(
            "Share link",
            [
                f"handle   {result['handle']}",
                result["url"],
                f"expires  {result['expires_at'].isoformat()}",
            ],
        )
    )


def _reserve(args: argparse.Namespace) -> None:
    from share import create_reservation_for
    from ui import panel, print_banner

    start = datetime.fromisoformat(args.start)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=args.minutes)
    print_banner()
    result = create_reservation_for(args.handle, start, end)
    print(
        panel(
            "Reservation",
            [
                f"id      {result['id']}",
                f"handle  {result['handle']}",
                f"start   {result['start_time']}",
                f"end     {result['end_time']}",
            ],
        )
    )


def _revoke(args: argparse.Namespace) -> None:
    from share import revoke_user
    from ui import panel, print_banner

    print_banner()
    result = revoke_user(args.handle)
    print(panel("Revoked", [result["handle"], "Sessions, future bookings, and SSH access were removed."]))


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
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{serve,setup,doctor,migrate,share,reserve,revoke,admin}",
    )

    serve = commands.add_parser("serve", help="Run the API, scheduler, and local SSH gateway")
    serve.add_argument("--host", default=os.environ.get("API_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("API_PORT", "9473")))
    serve.add_argument("--tunnel", action="store_true", help="Start a remote SSH tunnel (optional; requires a token)")
    serve.add_argument("--no-tunnel", action="store_true", help=argparse.SUPPRESS)
    serve.set_defaults(func=_serve)

    setup = commands.add_parser("setup", help="Write .env, install the storage helper, and pull the user image")
    setup.add_argument("--token", help="Remote SSH tunnel authtoken (stored in .env, not printed)")
    setup.add_argument("--skip-helper", action="store_true", help="Do not install the storage helper")
    setup.add_argument("--skip-image", action="store_true", help="Do not pull DOCKER_IMAGE")
    setup.add_argument("--skip-env", action="store_true", help="Do not prompt for or rewrite the environment file")
    setup.add_argument("--skip-postgres", action="store_true", help="Do not start PostgreSQL with Docker Compose")
    setup.add_argument("--cpu", action="store_true", help="Use the opengpu:cpu image and skip NVIDIA checks")
    setup.add_argument("--env-file", help="Path to write (default: .env, or ~/.config/opengpu/env when installed)")
    setup.set_defaults(func=_setup)

    doctor = commands.add_parser("doctor", help="Check that this host can run OpenGPU")
    doctor.add_argument("--cpu", action="store_true", help="Use the opengpu:cpu image and skip NVIDIA checks")
    doctor.set_defaults(func=_doctor)

    migrate_cmd = commands.add_parser("migrate", help="Apply the PostgreSQL schema or pending migrations")
    migrate_cmd.set_defaults(func=_migrate)

    share = commands.add_parser("share", help="Create a Personal-mode claim link")
    share.add_argument("handle")
    share.add_argument("--hours", type=int, default=None)
    share.set_defaults(func=_share)

    reserve = commands.add_parser("reserve", help="Create a reservation for a user")
    reserve.add_argument("handle")
    reserve.add_argument("--start", required=True, help="ISO-8601 start time")
    reserve.add_argument("--minutes", type=int, default=60)
    reserve.set_defaults(func=_reserve)

    revoke = commands.add_parser("revoke", help="Remove a user's sessions, bookings, and SSH key")
    revoke.add_argument("handle")
    revoke.set_defaults(func=_revoke)

    commands.add_parser("admin", help="Administration commands")
    args = parser.parse_args(argv)
    args.func(args)


def _hidden(name: str, func, argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog=f"opengpu {name}")
    args = parser.parse_args(argv)
    func(args)


if __name__ == "__main__":
    main()
