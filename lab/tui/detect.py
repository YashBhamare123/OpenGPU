"""Host detection for the lab TUI."""

from __future__ import annotations

import shutil
import subprocess


def nvidia_available() -> bool:
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool((result.stdout or "").strip())


def cookie_secure_for(origins: str) -> str:
    parts = [item.strip() for item in (origins or "").split(",") if item.strip()]
    if parts and all(item.startswith("https://") for item in parts):
        return "true"
    return "false"


def host_defaults() -> dict[str, str]:
    return {
        "SERVER_IP": "127.0.0.1",
        "DOCKER_BIND_IP": "127.0.0.1",
        "WORKSPACE_ROOT": "/var/lib/docker/opengpu-workspaces",
        "ALLOWED_ORIGINS": "http://127.0.0.1:9473,http://localhost:9473",
        "COOKIE_SECURE": "false",
    }
