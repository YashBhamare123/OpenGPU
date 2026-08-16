import os
import secrets
import socket
import string
import subprocess
import time
from datetime import datetime
from pathlib import Path

import docker

from config import settings
from mailer import deliver_credentials as send_credentials

APP_LABEL = "aiml-gpu-reservation"
SEED_LABEL = "aiml-storage-seed"
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


def _storage_root() -> Path:
    configured_root = Path(settings.workspace_root).expanduser()
    if not configured_root.is_absolute():
        raise RuntimeError("WORKSPACE_ROOT must be an absolute path")
    # The storage helper deliberately creates root-owned paths that the scheduler
    # cannot stat. Normalize lexically without traversing those directories;
    # the configured root is trusted deployment configuration, not user input.
    return Path(os.path.abspath(configured_root))


def _run_storage_helper(*args: str, timeout: int) -> None:
    subprocess.run(
        ["sudo", "-n", settings.storage_helper, *args],
        capture_output=True, text=True, check=True, timeout=timeout,
    )


def prepare_user_storage(
    user_id: int, workspace_gb: int = 2, temp_storage_gb: int = 100,
    convert: bool = False,
) -> tuple[Path, Path, Path, Path, Path]:
    if user_id < 1:
        raise ValueError("User ID must be positive")
    if workspace_gb < 1 or workspace_gb > 199:
        raise ValueError("Workspace storage must be between 1 and 199 GB")
    if temp_storage_gb < 1 or temp_storage_gb > 199:
        raise ValueError("Temporary storage must be between 1 and 199 GB")
    if workspace_gb + temp_storage_gb > 200:
        raise ValueError("Reservation storage must total no more than 200 GB")
    user_root = _storage_root() / "users" / str(user_id)
    workspace = user_root / "workspace"
    host_keys = user_root / "ssh-host-keys"
    scratch_home = user_root / "scratch" / "home"
    scratch_tmp = user_root / "scratch" / "tmp"
    scratch_etc = user_root / "scratch" / "etc"
    helper_args = ["prepare", str(user_id), str(workspace_gb), str(temp_storage_gb)]
    if convert:
        helper_args.append("convert")
    _run_storage_helper(*helper_args, timeout=300)
    return workspace, host_keys, scratch_home, scratch_tmp, scratch_etc


def storage_destination_has_user_files(destination: Path) -> bool:
    """True when a mount already holds data besides ext4's lost+found."""
    return any(path.name != "lost+found" for path in destination.iterdir())


def seed_scratch_etc(scratch_etc: Path) -> None:
    container = get_client().containers.create(
        image=settings.docker_image,
        entrypoint="/bin/bash",
        command=[
            "-c",
            "if [ ! -f /destination/passwd ]; then cp -a /etc/. /destination/; fi",
        ],
        volumes={str(scratch_etc): {"bind": "/destination", "mode": "rw"}},
        labels={"app": SEED_LABEL},
        network_disabled=True,
    )
    try:
        container.start()
        result = container.wait(timeout=60)
        if result.get("StatusCode", 1) != 0:
            logs = container.logs().decode("utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"Failed to seed container /etc: {logs}")
    finally:
        try:
            container.remove(force=True)
        except docker.errors.DockerException:
            pass


def release_user_storage(user_id: int, attempts: int = 3) -> None:
    if user_id < 1:
        raise ValueError("User ID must be positive")
    last_error = None
    for attempt in range(attempts):
        try:
            _run_storage_helper("release", str(user_id), timeout=60)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1)
    raise last_error


def teardown_scratch(user_id: int, attempts: int = 3) -> None:
    release_user_storage(user_id, attempts=attempts)


def user_storage_paths(
    user_id: int, workspace_gb: int = 2, temp_storage_gb: int = 100,
) -> tuple[Path, Path, Path, Path, Path]:
    return prepare_user_storage(user_id, workspace_gb, temp_storage_gb)


def provision_user(user_id: int, email: str, username: str, ssh_port: int,
                   container_name: str, volume_name: str, allow_legacy_volume: bool = False,
                   email_credentials: bool = True, reservation_start: datetime | None = None,
                   reservation_end: datetime | None = None, workspace_gb: int = 2,
                   temp_storage_gb: int = 100) -> str:
    if workspace_gb < 1 or temp_storage_gb < 1 or workspace_gb + temp_storage_gb > 200:
        raise ValueError("Reservation storage must total no more than 200 GB")
    password = random_password()
    password_hash = linux_password_hash(password)
    container = _get_owned_container(container_name, user_id)
    if container is not None:
        container.reload()
        if container.status == "running":
            raise RuntimeError("Refusing to replace a running provisioning container")
        container.remove()
    workspace, host_keys, scratch_home, scratch_tmp, scratch_etc = prepare_user_storage(
        user_id, workspace_gb, temp_storage_gb, convert=True,
    )
    seed_scratch_etc(scratch_etc)
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
            str(scratch_home): {"bind": f"/home/{username}", "mode": "rw"},
            str(scratch_tmp): {"bind": "/tmp", "mode": "rw"},
            str(scratch_etc): {"bind": "/etc", "mode": "rw"},
        },
        environment={"TEAM_NAME": username, "TEAM_PASSWORD_HASH": password_hash,
                     "WORKSPACE_GB": str(workspace_gb), "TEMP_STORAGE_GB": str(temp_storage_gb)},
        device_requests=[docker.types.DeviceRequest(count=1, capabilities=[["gpu"]])],
        mem_limit=settings.memory_limit,
        nano_cpus=settings.cpu_limit * 1_000_000_000,
        pids_limit=settings.pids_limit,
        shm_size=settings.shm_size,
        restart_policy={"Name": "no"},
        read_only=True,
        tmpfs={"/run": "rw,nosuid,nodev,mode=755"},
    )
    if email_credentials:
        try:
            send_credentials(email, username, password, ssh_port, reservation_start, reservation_end)
        except Exception:
            # Plaintext is deliberately not retained. Recreate with a new password on retry.
            try:
                remove_container(container)
            except Exception:  # noqa: BLE001
                try:
                    container.remove(force=True)
                except docker.errors.DockerException:
                    pass
            raise
    return password_hash


def managed_containers():
    return get_client().containers.list(all=True, filters={"label": f"app={APP_LABEL}"})


def start_container(
    name: str, user_id: int, workspace_gb: int = 2, temp_storage_gb: int = 100,
) -> None:
    container = _get_owned_container(name, user_id)
    if container is None:
        raise RuntimeError(f"Managed container {name} is missing")
    _workspace, _host_keys, _scratch_home, _scratch_tmp, scratch_etc = prepare_user_storage(
        user_id, workspace_gb, temp_storage_gb,
    )
    seed_scratch_etc(scratch_etc)
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
    raw_user_id = container.labels.get("aiml.user_id", "")
    if not raw_user_id.isdigit() or int(raw_user_id) < 1:
        raise RuntimeError("Managed container is missing a valid aiml.user_id label")
    user_id = int(raw_user_id)
    container.reload()
    if container.status == "running":
        stop_container(container, timeout=timeout)
    container.remove()
    release_user_storage(user_id)
