from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

from config import CPU_IMAGE, GPU_IMAGE

# Unprivileged ports that common web/SSH stacks do not occupy (8000, 8080, 2222, 3000).
API_PORT = 9473
SSH_GATEWAY_PORT = 9474

SUMMARY_KEYS = (
    "CPU_ONLY",
    "DOCKER_IMAGE",
    "CONTAINER_CPUS",
    "CONTAINER_MEMORY",
    "CONTAINER_SHM",
    "SSH_PUBLIC_PORT",
    "API_PORT",
    "SERVER_IP",
    "DOCKER_BIND_IP",
    "ALLOWED_ORIGINS",
    "COOKIE_SECURE",
    "WORKSPACE_ROOT",
)


def cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def memory_gb() -> int:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return 8
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            kb = int(line.split()[1])
            return max(1, kb // 1024 // 1024)
    return 8


def container_cpus(available: int | None = None) -> int:
    available = cpu_count() if available is None else max(1, available)
    return max(1, min(16, available))


def container_memory_gb(total_gb: int | None = None) -> int:
    total_gb = memory_gb() if total_gb is None else max(1, total_gb)
    reserved = 2 if total_gb > 4 else max(1, total_gb // 2)
    usable = total_gb - reserved if total_gb > reserved else max(1, total_gb // 2)
    return max(1, min(32, usable))


def container_shm(memory_limit_gb: int) -> str:
    return f"{max(1, min(16, memory_limit_gb // 4 or 1))}g"


def nvidia_available() -> bool:
    if shutil.which("nvidia-smi") is None:
        return False
    if shutil.which("nvidia-container-runtime") is None and shutil.which("nvidia-container-cli") is None:
        return False
    result = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, check=False)
    return result.returncode == 0 and bool((result.stdout or "").strip())


def free_tcp_port(start: int, host: str = "127.0.0.1", span: int = 20) -> int:
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    return start


def routable_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        address = sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
    if address.startswith(("127.", "169.254.")):
        return "127.0.0.1"
    return address


def cookie_secure_for(origins: str) -> str:
    parts = [item.strip() for item in origins.split(",") if item.strip()]
    if parts and all(item.startswith("https://") for item in parts):
        return "true"
    return "false"


def workspace_root() -> str:
    preferred = Path("/var/lib/docker/opengpu-workspaces")
    if preferred.parent.is_dir() and os.access(preferred.parent, os.W_OK):
        return str(preferred)
    return str(Path.home() / ".local/share/opengpu/workspaces")


def allowed_origins(api_port: int) -> str:
    origins = [f"http://127.0.0.1:{api_port}", f"http://localhost:{api_port}"]
    address = routable_ipv4()
    if address != "127.0.0.1":
        extra = f"http://{address}:{api_port}"
        if extra not in origins:
            origins.append(extra)
    domain = (os.environ.get("NGROK_DOMAIN") or "").strip().strip("/")
    if domain:
        origin = domain if domain.startswith("https://") else f"https://{domain}"
        if origin not in origins:
            origins.append(origin)
    return ",".join(origins)


def host_defaults() -> dict[str, str]:
    cpus = container_cpus()
    memory = container_memory_gb()
    api_port = free_tcp_port(API_PORT)
    ssh_port = free_tcp_port(SSH_GATEWAY_PORT)
    cpu_only = not nvidia_available()
    origins = allowed_origins(api_port)
    address = routable_ipv4()
    return {
        "SERVER_IP": address,
        "DOCKER_BIND_IP": address,
        "WORKSPACE_ROOT": workspace_root(),
        "ALLOWED_ORIGINS": origins,
        "COOKIE_SECURE": cookie_secure_for(origins),
        "DOCKER_IMAGE": CPU_IMAGE if cpu_only else GPU_IMAGE,
        "CPU_ONLY": "true" if cpu_only else "false",
        "SSH_PUBLIC_PORT": str(ssh_port),
        "API_HOST": "127.0.0.1",
        "API_PORT": str(api_port),
        "CONTAINER_MEMORY": f"{memory}g",
        "CONTAINER_CPUS": str(cpus),
        "CONTAINER_SHM": container_shm(memory),
    }


def format_summary(detected: dict[str, str]) -> str:
    lines = ["Detected host defaults (press Enter to accept):"]
    for key in SUMMARY_KEYS:
        if key in detected:
            lines.append(f"  {key}={detected[key]}")
    return "\n".join(lines)
