import secrets
import socket
import string
import subprocess
from datetime import datetime
from pathlib import Path

import docker

from config import settings
from mailer import send_credentials


APP_LABEL = "aiml-gpu-reservation"
_client = None


def get_client():
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def random_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def linux_password_hash(password: str) -> str:
    result = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"], input=password, text=True,
        capture_output=True, check=True, timeout=10,
    )
    return result.stdout.strip()


def labels(user_id: int) -> dict[str, str]:
    return {"app": APP_LABEL, "aiml.user_id": str(user_id)}


def _get_owned_container(name: str, user_id: int):
    try:
        container = get_client().containers.get(name)
    except docker.errors.NotFound:
        return None
    if container.labels.get("app") != APP_LABEL or container.labels.get("aiml.user_id") != str(user_id):
        raise RuntimeError(f"Container name {name} is occupied by an unmanaged resource")
    return container


def _get_owned_volume(name: str, user_id: int, allow_legacy: bool = False):
    try:
        volume = get_client().volumes.get(name)
    except docker.errors.NotFound:
        return get_client().volumes.create(name=name, labels=labels(user_id))
    attrs = volume.attrs.get("Labels") or {}
    if allow_legacy and not attrs:
        return volume
    if attrs.get("app") != APP_LABEL or attrs.get("aiml.user_id") != str(user_id):
        raise RuntimeError(f"Volume name {name} is occupied by an unmanaged resource")
    return volume


def user_storage_paths(user_id: int) -> tuple[Path, Path]:
    if user_id < 1:
        raise ValueError("User ID must be positive")
    configured_root = Path(settings.workspace_root).expanduser()
    if not configured_root.is_absolute():
        raise RuntimeError("WORKSPACE_ROOT must be an absolute path")
    root = configured_root.resolve()
    user_root = root / "users" / str(user_id)
    workspace = user_root / "workspace"
    host_keys = user_root / "ssh-host-keys"
    for path, mode in ((root, 0o750), (user_root, 0o750), (workspace, 0o750), (host_keys, 0o700)):
        path.mkdir(mode=mode, parents=True, exist_ok=True)
        path.chmod(mode)
    return workspace, host_keys


def provision_user(user_id: int, email: str, username: str, ssh_port: int,
                   container_name: str, volume_name: str, allow_legacy_volume: bool = False,
                   email_credentials: bool = True, reservation_start: datetime | None = None,
                   reservation_end: datetime | None = None) -> str:
    password = random_password()
    password_hash = linux_password_hash(password)
    workspace, host_keys = user_storage_paths(user_id)
    container = _get_owned_container(container_name, user_id)
    if container is not None:
        container.reload()
        if container.status == "running":
            raise RuntimeError("Refusing to replace a running provisioning container")
        container.remove()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((settings.docker_bind_ip, ssh_port))
    container = get_client().containers.create(
        image=settings.docker_image,
        name=container_name,
        hostname=container_name,
        labels=labels(user_id),
        ports={"22/tcp": (settings.docker_bind_ip, ssh_port)},
        volumes={
            str(workspace): {"bind": "/workspace", "mode": "rw"},
            str(host_keys): {"bind": "/etc/ssh/host_keys", "mode": "rw"},
        },
        environment={"TEAM_NAME": username, "TEAM_PASSWORD_HASH": password_hash},
        device_requests=[docker.types.DeviceRequest(count=1, capabilities=[["gpu"]])],
        mem_limit=settings.memory_limit,
        nano_cpus=settings.cpu_limit * 1_000_000_000,
        pids_limit=settings.pids_limit,
        shm_size=settings.shm_size,
        restart_policy={"Name": "no"},
    )
    if email_credentials:
        try:
            send_credentials(email, username, password, ssh_port, reservation_start, reservation_end)
        except Exception:
            # Plaintext is deliberately not retained. Recreate with a new password on retry.
            try:
                container.remove(force=True)
            except docker.errors.DockerException:
                pass
            raise
    return password_hash


def managed_containers():
    return get_client().containers.list(all=True, filters={"label": f"app={APP_LABEL}"})


def start_container(name: str, user_id: int) -> None:
    container = _get_owned_container(name, user_id)
    if container is None:
        raise RuntimeError(f"Managed container {name} is missing")
    container.start()


def stop_container(container, timeout: int = 15) -> None:
    if container.labels.get("app") != APP_LABEL:
        raise RuntimeError("Refusing to stop an unmanaged container")
    container.stop(timeout=timeout)
    container.reload()
    if container.status == "running":
        raise RuntimeError(f"Container {container.name} did not stop")


def remove_container(container, timeout: int = 15) -> None:
    if container.labels.get("app") != APP_LABEL:
        raise RuntimeError("Refusing to remove an unmanaged container")
    container.reload()
    if container.status == "running":
        stop_container(container, timeout=timeout)
    container.remove()
