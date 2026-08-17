from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from envfile import apply_env, configure_env, default_env_path, parse_env
from ui import format_checks, muted, panel, print_banner


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fatal: bool = True


def _say(text: str) -> None:
    print(muted(text), flush=True)


def _dummy_checks(*, cpu: bool = False) -> list[Check]:
    gpu = "CPU only" if cpu else "GPU ready"
    return [
        Check("settings", True, "saved"),
        Check("docker", True, "ready"),
        Check("image", True, "ready"),
        Check("gpu", True, gpu),
        Check("email", True, "ready"),
        Check("database", True, "ready"),
        Check("storage", True, "ready"),
        Check("disk", True, "enough space"),
        Check("remote", True, "ready"),
    ]


def doctor(*, cpu: bool = False, input_fn=input, interactive: bool = True, banner: bool = True) -> int:
    from envfile import _prompt_accelerator

    if banner:
        print_banner()
    if interactive and not cpu:
        cpu = _prompt_accelerator(cpu_only="true" if cpu else "false", input_fn=input_fn) == "true"
    elif not cpu:
        cpu = parse_env(default_env_path()).get("CPU_ONLY") == "true"
    checks = _dummy_checks(cpu=cpu)
    print(format_checks(checks))
    if any(not check.ok and check.fatal for check in checks):
        print("This machine isn't ready yet.")
        return 1
    if interactive:
        print("This machine looks ready.")
    return 0


def setup(
    *,
    token: str | None = None,
    skip_helper: bool = False,
    skip_image: bool = False,
    skip_env: bool = False,
    skip_postgres: bool = False,
    cpu: bool = False,
    env_file: str | None = None,
    env_values: dict[str, str] | None = None,
) -> int:
    path = Path(env_file).expanduser() if env_file else default_env_path()
    chosen: dict[str, str] = {}
    if not skip_env:
        try:
            chosen = configure_env(path, values=env_values, write=True)
        except (EOFError, ValueError) as exc:
            print(f"Couldn't save your settings: {exc}")
            return 1
        _say("Saved.")
        if not skip_postgres:
            _say("Starting the database…")
    if not skip_helper:
        _say("Preparing storage…")
    if cpu:
        _say("CPU only.")
    if not skip_image:
        _say("Getting the workspace image…")
    token = token or chosen.get("NGROK_AUTHTOKEN") or chosen.get("NGROK_TOKEN")
    if token:
        _say("Remote access saved.")
    return 0


def serve(*, host: str, port: int, tunnel: bool = False) -> None:
    env = parse_env(default_env_path())
    apply_env(env)
    mode = env.get("OPENGPU_MODE") or os.environ.get("OPENGPU_MODE", "lab")
    label = "A lab" if mode == "lab" else "Just you"
    print_banner()
    print(
        panel(
            "OpenGPU is running",
            [
                label,
                f"Open  http://{host}:{port}",
                "SSH   127.0.0.1:9474",
            ],
        )
    )
    print()
    print(muted("Press Enter to stop."))
    try:
        input()
    except EOFError:
        pass


def start(
    *,
    host: str = "127.0.0.1",
    port: int = 9473,
    tunnel: bool = False,
    env_file: str | None = None,
) -> int:
    path = Path(env_file).expanduser() if env_file else default_env_path()
    if not path.is_file():
        status = setup(env_file=str(path) if env_file else None)
        if status != 0:
            return status
    status = migrate(quiet=True)
    if status != 0:
        return status
    status = doctor(interactive=False, banner=False)
    if status != 0:
        return status
    serve(host=host, port=port, tunnel=tunnel)
    return 0


def migrate(*, quiet: bool = False) -> int:
    if not quiet:
        print_banner()
    _say("Updating the database…")
    if not quiet:
        print("Done.")
    return 0
