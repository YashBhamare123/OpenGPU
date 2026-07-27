import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get("DATABASE_URL", "")
    server_ip: str = os.environ.get("SERVER_IP", "127.0.0.1")
    docker_bind_ip: str = os.environ.get("DOCKER_BIND_IP", "127.0.0.1")
    docker_image: str = os.environ.get("DOCKER_IMAGE", "opengpu:ml")
    workspace_root: str = os.environ.get("WORKSPACE_ROOT", "/home/user/devbox-workspaces")
    ssh_port_start: int = _int("SSH_PORT_START", 22001)
    ssh_port_end: int = _int("SSH_PORT_END", 32000)
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    smtp_from: str = os.environ.get("SMTP_FROM", "")
    session_hours: int = _int("SESSION_HOURS", 12)
    otp_minutes: int = _int("OTP_MINUTES", 10)
    otp_max_attempts: int = _int("OTP_MAX_ATTEMPTS", 5)
    poll_interval: int = _int("POLL_INTERVAL", 5)
    memory_limit: str = os.environ.get("CONTAINER_MEMORY", "32g")
    cpu_limit: int = _int("CONTAINER_CPUS", 16)
    pids_limit: int = _int("CONTAINER_PIDS", 4096)
    storage_limit: str = os.environ.get("CONTAINER_STORAGE", "16g")
    workspace_limit: str = os.environ.get("WORKSPACE_STORAGE", "2g")
    shm_size: str = os.environ.get("CONTAINER_SHM", "16g")
    cookie_secure: bool = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
    allowed_origins: tuple[str, ...] = tuple(
        value.strip() for value in os.environ.get("ALLOWED_ORIGINS", "").split(",") if value.strip()
    )


settings = Settings()
