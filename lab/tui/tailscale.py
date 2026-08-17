from __future__ import annotations

import json
import shutil
import subprocess

SIGN_IN_URL = "https://login.tailscale.com/start"


def available() -> bool:
    return shutil.which("tailscale") is not None


def _status() -> dict:
    if not available():
        return {}
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        return json.loads(result.stdout or "{}")
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return {}


def logged_in() -> bool:
    return _status().get("BackendState") == "Running"


def login_url() -> str:
    return (_status().get("AuthURL") or "").strip() or SIGN_IN_URL


def enable_sharing(*, api_port: int = 9473, ssh_port: int = 9474) -> dict[str, str]:
    return {
        "ui_url": "",
        "api_port": str(api_port),
        "ssh_port": str(ssh_port),
    }
