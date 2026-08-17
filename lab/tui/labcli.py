from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent
if str(LAB_DIR) not in sys.path:
    sys.path.insert(0, str(LAB_DIR))


def _start(args: argparse.Namespace) -> None:
    from host import start

    raise SystemExit(
        start(
            host=getattr(args, "host", os.environ.get("API_HOST", "127.0.0.1")),
            port=getattr(args, "port", int(os.environ.get("API_PORT", "9473"))),
            tunnel=getattr(args, "tunnel", False) and not getattr(args, "no_tunnel", False),
            env_file=getattr(args, "env_file", None),
        )
    )


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


def _doctor(args: argparse.Namespace) -> None:
    from host import doctor

    raise SystemExit(doctor(cpu=args.cpu))


def _serve(args: argparse.Namespace) -> None:
    from host import serve

    serve(host=args.host, port=args.port, tunnel=args.tunnel and not args.no_tunnel)


def _migrate(_args: argparse.Namespace) -> None:
    from host import migrate

    raise SystemExit(migrate())


def _share(args: argparse.Namespace) -> None:
    from share import create_claim
    from ui import panel, print_banner

    print_banner()
    result = create_claim(args.handle, hours=args.hours)
    print(
        panel(
            "Share link",
            [
                result["handle"],
                result["url"],
                f"Expires {result['expires_at'].strftime('%b %d, %H:%M')} UTC",
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
            "Booked",
            [
                result["handle"],
                result["start_time"],
                result["end_time"],
            ],
        )
    )


def _revoke(args: argparse.Namespace) -> None:
    from share import revoke_user
    from ui import panel, print_banner

    print_banner()
    result = revoke_user(args.handle)
    print(panel("Access removed", [result["handle"]]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opengpu",
        description="OpenGPU",
        epilog="Run opengpu with no arguments to set up and start. Other commands are for debugging.",
    )
    parser.set_defaults(func=_start, host=os.environ.get("API_HOST", "127.0.0.1"), port=int(os.environ.get("API_PORT", "9473")), tunnel=False, no_tunnel=False, env_file=None)
    commands = parser.add_subparsers(dest="command", metavar="command")

    setup = commands.add_parser("setup", help="Redo setup without starting")
    setup.add_argument("--token")
    setup.add_argument("--skip-helper", action="store_true")
    setup.add_argument("--skip-image", action="store_true")
    setup.add_argument("--skip-env", action="store_true")
    setup.add_argument("--skip-postgres", action="store_true")
    setup.add_argument("--cpu", action="store_true")
    setup.add_argument("--env-file")
    setup.set_defaults(func=_setup)

    doctor = commands.add_parser("doctor", help="Check this machine")
    doctor.add_argument("--cpu", action="store_true")
    doctor.set_defaults(func=_doctor)

    serve = commands.add_parser("serve", help="Start without setup")
    serve.add_argument("--host", default=os.environ.get("API_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("API_PORT", "9473")))
    serve.add_argument("--tunnel", action="store_true")
    serve.add_argument("--no-tunnel", action="store_true")
    serve.set_defaults(func=_serve)

    migrate_cmd = commands.add_parser("migrate", help="Update the database")
    migrate_cmd.set_defaults(func=_migrate)

    share = commands.add_parser("share", help="Create a share link")
    share.add_argument("handle")
    share.add_argument("--hours", type=int, default=None)
    share.set_defaults(func=_share)

    reserve = commands.add_parser("reserve", help="Book time for someone")
    reserve.add_argument("handle")
    reserve.add_argument("--start", required=True)
    reserve.add_argument("--minutes", type=int, default=60)
    reserve.set_defaults(func=_reserve)

    revoke = commands.add_parser("revoke", help="Remove someone's access")
    revoke.add_argument("handle")
    revoke.set_defaults(func=_revoke)

    return parser


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
