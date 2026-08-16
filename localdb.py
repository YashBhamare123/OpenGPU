import secrets
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import quote_plus

from paths import postgres_path

PROJECT = "opengpu"
PGUSER = "opengpu"
PGDATABASE = "opengpu"
CONTAINER = "opengpu-postgres"
DEFAULT_PORT = 5432


def data_dir() -> Path:
    return Path.home() / ".local/share/opengpu"


def _compose_command() -> list[str] | None:
    docker = shutil.which("docker")
    if docker is None:
        return None
    probe = subprocess.run([docker, "compose", "version"], capture_output=True, text=True, check=False)
    if probe.returncode == 0:
        return [docker, "compose"]
    legacy = shutil.which("docker-compose")
    if legacy:
        return [legacy]
    return None


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _free_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + 20):
        if not _port_open(port):
            return port
    raise RuntimeError(f"no free TCP port in {start}-{start + 19} for PostgreSQL")


def _load_pg_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value
    return values


def _write_pg_env(path: Path, password: str, port: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"POSTGRES_USER={PGUSER}\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB={PGDATABASE}\n"
        f"OPENGPU_PGPORT={port}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def database_url(password: str, port: int) -> str:
    return f"postgresql://{PGUSER}:{quote_plus(password)}@127.0.0.1:{port}/{PGDATABASE}"


def wait_for_postgres(port: int, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(port):
            check = subprocess.run(
                ["docker", "exec", CONTAINER, "pg_isready", "-U", PGUSER, "-d", PGDATABASE],
                capture_output=True, text=True, check=False,
            )
            if check.returncode == 0:
                return
        time.sleep(1)
    raise RuntimeError("PostgreSQL started but did not become ready")


def ensure_local_postgres() -> str:
    compose = _compose_command()
    if compose is None:
        raise RuntimeError("Docker Compose is not available; install Docker or pass DATABASE_URL")
    compose_file = postgres_path("compose.yaml")
    if not compose_file.is_file():
        raise RuntimeError(f"missing {compose_file}")
    env_path = data_dir() / "postgres.env"
    existing = _load_pg_env(env_path)
    password = existing.get("POSTGRES_PASSWORD") or secrets.token_urlsafe(24)
    if existing.get("OPENGPU_PGPORT"):
        port = int(existing["OPENGPU_PGPORT"])
    elif _port_open(DEFAULT_PORT):
        port = _free_port(DEFAULT_PORT + 1)
    else:
        port = DEFAULT_PORT
    _write_pg_env(env_path, password, port)
    command = [
        *compose,
        "--project-name", PROJECT,
        "-f", str(compose_file),
        "--env-file", str(env_path),
        "up", "-d",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:300] or "docker compose up failed"
        raise RuntimeError(detail)
    wait_for_postgres(port)
    return database_url(password, port)
