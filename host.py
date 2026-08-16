import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from config import settings
from database import get_connection
from paths import script_path

REQUIRED_ENV = (
    "DATABASE_URL",
    "SERVER_IP",
    "DOCKER_BIND_IP",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_FROM",
    "ALLOWED_ORIGINS",
    "COOKIE_SECURE",
)
REQUIRED_TABLES = {
    "teams",
    "reservations",
    "auth_challenges",
    "sessions",
    "provisioning_jobs",
    "audit_events",
    "service_heartbeats",
}
REQUIRED_TEAM_COLUMNS = {
    "ssh_password_hash",
    "provisioning_state",
    "volume_name",
    "legacy_volume",
}
REQUIRED_RESERVATION_COLUMNS = {"duration_override", "workspace_gb", "temp_storage_gb"}
HELPER_SUDO_PROBES = (
    ("prepare", "1", "2", "3"),
    ("prepare", "1", "2", "3", "convert"),
    ("release", "1"),
)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fatal: bool = True


def _run(command: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def check_configuration() -> Check:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        return Check("configuration", False, "missing " + ", ".join(missing))
    if settings.ssh_port_start < 1024 or settings.ssh_port_end > 65535:
        return Check("configuration", False, "SSH port range must stay between 1024 and 65535")
    if settings.ssh_port_start > settings.ssh_port_end:
        return Check("configuration", False, "SSH_PORT_START must be less than or equal to SSH_PORT_END")
    if settings.reservation_limit_minutes < 15 or settings.reservation_limit_minutes % 15:
        return Check("configuration", False, "RESERVATION_LIMIT_MINUTES must be at least 15 and divisible by 15")
    if settings.cookie_secure and not all(origin.startswith("https://") for origin in settings.allowed_origins):
        return Check("configuration", False, "COOKIE_SECURE=true requires HTTPS values in ALLOWED_ORIGINS")
    return Check("configuration", True, "required settings are present")


def check_docker() -> Check:
    if shutil.which("docker") is None:
        return Check("docker", False, "docker is not on PATH; install Docker Engine first")
    result = _run(["docker", "info"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "docker info failed"
        return Check("docker", False, f"cannot access Docker: {detail[:200]}")
    return Check("docker", True, "docker info succeeded")


def check_nvidia() -> Check:
    if shutil.which("nvidia-smi") is None:
        return Check("nvidia", False, "nvidia-smi is not on PATH; install the NVIDIA driver first")
    result = _run(["nvidia-smi", "-L"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "nvidia-smi failed"
        return Check("nvidia", False, detail[:200])
    if shutil.which("nvidia-container-runtime") is None and shutil.which("nvidia-container-cli") is None:
        return Check(
            "nvidia",
            False,
            "NVIDIA Container Toolkit is missing (nvidia-container-runtime or nvidia-container-cli)",
        )
    gpus = (result.stdout or "").strip() or "GPU visible"
    return Check("nvidia", True, gpus.splitlines()[0])


def check_smtp() -> Check:
    if not settings.smtp_host or not settings.smtp_from:
        return Check("smtp", False, "SMTP_HOST and SMTP_FROM must be set")
    try:
        with socket.create_connection((settings.smtp_host, settings.smtp_port), timeout=3):
            pass
    except OSError as exc:
        return Check("smtp", False, f"cannot reach {settings.smtp_host}:{settings.smtp_port}: {exc}")
    return Check("smtp", True, f"{settings.smtp_host}:{settings.smtp_port} accepted a TCP connection")


def check_database() -> Check:
    try:
        connection = get_connection()
    except Exception as exc:  # noqa: BLE001
        return Check("database", False, f"cannot connect: {exc}")
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        }
        team_columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='teams'"
            )
        }
        reservation_columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='reservations'"
            )
        }
    except Exception as exc:  # noqa: BLE001
        return Check("database", False, f"schema query failed: {exc}")
    finally:
        connection.close()
    missing = []
    if REQUIRED_TABLES - tables:
        missing.append("tables: " + ", ".join(sorted(REQUIRED_TABLES - tables)))
    if REQUIRED_TEAM_COLUMNS - team_columns:
        missing.append("teams columns: " + ", ".join(sorted(REQUIRED_TEAM_COLUMNS - team_columns)))
    if REQUIRED_RESERVATION_COLUMNS - reservation_columns:
        missing.append("reservations columns: " + ", ".join(sorted(REQUIRED_RESERVATION_COLUMNS - reservation_columns)))
    if missing:
        return Check("database", False, "not migrated (" + "; ".join(missing) + ")")
    return Check("database", True, "required tables and columns are present")


def check_storage_helper() -> Check:
    helper = Path(settings.storage_helper)
    if not helper.is_absolute() or not os.access(helper, os.X_OK):
        return Check(
            "storage-helper",
            False,
            f"{helper} is not an executable absolute path; run: opengpu setup",
        )
    for args in HELPER_SUDO_PROBES:
        result = _run(["sudo", "-n", "-l", str(helper), *args])
        if result.returncode != 0:
            return Check(
                "storage-helper",
                False,
                "passwordless sudo for the storage helper is missing; run: opengpu setup",
            )
    return Check("storage-helper", True, f"{helper} is installed and sudoable")


def check_workspace() -> Check:
    root = Path(settings.workspace_root)
    if not root.is_absolute():
        return Check("workspace", False, "WORKSPACE_ROOT must be an absolute path")
    probe = root
    usage = None
    while True:
        try:
            usage = os.statvfs(probe)
            break
        except OSError as exc:
            if probe == probe.parent:
                return Check("workspace", False, f"cannot inspect {root}: {exc}", fatal=False)
            probe = probe.parent
    free_gb = (usage.f_bavail * usage.f_frsize) // (1024 ** 3)
    needed = None
    try:
        connection = get_connection()
        try:
            row = connection.execute(
                """SELECT temp_storage_gb FROM reservations
                   WHERE NOT cancelled AND end_time > NOW()
                   ORDER BY start_time LIMIT 1"""
            ).fetchone()
        finally:
            connection.close()
        if row:
            needed = row[0]
    except Exception:  # noqa: BLE001
        needed = None
    if needed is not None and free_gb < needed:
        return Check(
            "workspace",
            False,
            f"{root} has {free_gb} GB free; the next reservation needs {needed} GB of scratch disk",
            fatal=False,
        )
    return Check("workspace", True, f"{root} has {free_gb} GB free on {probe}")


def ensure_image() -> Check:
    if shutil.which("docker") is None:
        return Check("image", False, "docker is not on PATH")
    inspect = _run(["docker", "image", "inspect", settings.docker_image])
    if inspect.returncode == 0:
        return Check("image", True, settings.docker_image)
    print(f"Pulling {settings.docker_image}...", flush=True)
    pull = _run(["docker", "pull", settings.docker_image], timeout=3600)
    if pull.returncode != 0:
        detail = (pull.stderr or pull.stdout).strip()[:300] or "docker pull failed"
        return Check("image", False, f"could not pull {settings.docker_image}: {detail}")
    return Check("image", True, f"pulled {settings.docker_image}")


def check_image() -> Check:
    return ensure_image()


def check_remote_access() -> Check:
    from tunnel import ngrok_token

    token = ngrok_token()
    if not token:
        return Check(
            "remote-access",
            False,
            "no tunnel token; SSH stays on the local network. Run: opengpu setup --token <authtoken>",
            fatal=False,
        )
    if shutil.which("ngrok") is None:
        return Check("remote-access", False, "tunnel token is set but ngrok is not on PATH")
    result = _run(["ngrok", "config", "check"])
    if result.returncode != 0:
        return Check("remote-access", False, "ngrok is not configured; rerun opengpu setup --token")
    return Check("remote-access", True, f"tunnel ready on localhost:{settings.ssh_public_port}")


def collect_checks() -> list[Check]:
    return [
        check_configuration(),
        check_docker(),
        check_image(),
        check_nvidia(),
        check_smtp(),
        check_database(),
        check_storage_helper(),
        check_workspace(),
    ]


def format_report(checks: list[Check]) -> str:
    lines = []
    for check in checks:
        if check.ok:
            status = "ok  "
        elif check.fatal:
            status = "fail"
        else:
            status = "warn"
        lines.append(f"{status}  {check.name}: {check.detail}")
    return "\n".join(lines)


def doctor() -> int:
    checks = collect_checks()
    print(format_report(checks))
    if any(not check.ok and check.fatal for check in checks):
        print("Host is not ready. Fix the failing checks, then rerun: opengpu doctor", file=sys.stderr)
        return 1
    print("Host checks passed.")
    return 0


def setup(*, token: str | None = None, skip_helper: bool = False, skip_image: bool = False) -> int:
    from paths import ROOT
    from tunnel import configure_agent, persist_token

    if not skip_helper:
        status = init_host()
        if status != 0:
            return status
    if not skip_image:
        image = ensure_image()
        print(f"{'ok' if image.ok else 'fail'}  {image.name}: {image.detail}")
        if not image.ok:
            return 1
    if token:
        os.environ["NGROK_AUTHTOKEN"] = token
        try:
            configure_agent(token)
        except Exception as exc:  # noqa: BLE001
            print(f"Could not store the remote-access token: {exc}", file=sys.stderr)
            return 1
        persist_token(ROOT / ".env", token)
        print("Remote SSH tunnel token saved.")
    print("Setup complete. Next: opengpu migrate && opengpu doctor && opengpu serve")
    return 0


def serve(*, host: str, port: int, tunnel: bool = False) -> None:
    import threading

    import uvicorn

    from gateway import serve_gateway
    from scheduler import run as run_scheduler

    image = ensure_image()
    if not image.ok:
        print(f"fail  image: {image.detail}", file=sys.stderr)
        raise SystemExit(1)

    stop = threading.Event()
    workers: list[threading.Thread] = []
    ngrok = None

    def scheduler_worker() -> None:
        try:
            run_scheduler()
        finally:
            stop.set()

    workers.append(threading.Thread(target=scheduler_worker, name="scheduler", daemon=True))
    workers.append(threading.Thread(target=serve_gateway, args=(stop,), name="ssh-gateway", daemon=True))
    for worker in workers:
        worker.start()

    if tunnel:
        from tunnel import ngrok_token, start_tunnel, wait_for_endpoint

        if not ngrok_token():
            print("No NGROK_AUTHTOKEN; serving locally.", file=sys.stderr, flush=True)
        else:
            ngrok = start_tunnel(settings.ssh_public_port)
            ssh_host, ssh_port = wait_for_endpoint(ngrok)
            os.environ["OPENGPU_SSH_HOST"] = ssh_host
            os.environ["OPENGPU_SSH_PORT"] = str(ssh_port)
            print(f"Remote SSH: ssh <user>@{ssh_host} -p {ssh_port}", flush=True)

    print(f"SSH gateway: {settings.ssh_gateway_bind}:{settings.ssh_public_port}", flush=True)
    print(f"API: http://{host}:{port}", flush=True)

    try:
        uvicorn.run("api:app", host=host, port=port)
    finally:
        stop.set()
        if ngrok is not None and ngrok.poll() is None:
            ngrok.terminate()
            try:
                ngrok.wait(timeout=5)
            except Exception:  # noqa: BLE001
                ngrok.kill()


def init_host() -> int:
    installer = script_path("install-storage-helper")
    if not installer.is_file():
        print(f"Missing storage helper installer: {installer}", file=sys.stderr)
        return 1
    if not Path(settings.workspace_root).is_absolute():
        print("WORKSPACE_ROOT must be an absolute path.", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env["WORKSPACE_ROOT"] = settings.workspace_root
    command = ["sudo", str(installer)]
    print(f"Installing storage helper for {settings.workspace_root}...")
    result = subprocess.run(command, env=env, check=False)
    if result.returncode != 0:
        print("Storage helper install failed. Run the command from the scheduler account with sudo.", file=sys.stderr)
        return result.returncode or 1
    print("Storage helper installed. Next: opengpu doctor")
    return 0
