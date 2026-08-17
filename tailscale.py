from __future__ import annotations

import json
import os
import shutil
import subprocess
from urllib.parse import urlparse

from config import settings


def _run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def available() -> bool:
    return shutil.which("tailscale") is not None


def status_payload() -> dict:
    result = _run(["tailscale", "status", "--json"])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "tailscale status failed").strip()[:300])
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("tailscale status returned invalid JSON") from exc


def logged_in() -> bool:
    try:
        payload = status_payload()
    except RuntimeError:
        return False
    backend = str(payload.get("BackendState") or "")
    return backend == "Running" and bool(payload.get("Self"))


def funnel_url(payload: dict | None = None) -> str:
    payload = payload if payload is not None else status_payload()
    self_node = payload.get("Self") or {}
    dns = str(self_node.get("DNSName") or "").rstrip(".")
    if dns:
        return f"https://{dns}"
    for key in ("MagicDNSSuffix",):
        suffix = payload.get(key)
        if suffix:
            return f"https://{str(suffix).rstrip('.')}"
    return ""


def configure_funnel(*, api_port: int, ssh_port: int) -> dict[str, str]:
    if not available():
        raise RuntimeError("tailscale is not on PATH. Install Tailscale, then rerun setup.")
    if not logged_in():
        raise RuntimeError("Tailscale is installed but not logged in. Run: tailscale login")
    serve = _run(["tailscale", "funnel", "--bg", str(api_port)], timeout=60)
    if serve.returncode != 0:
        detail = (serve.stderr or serve.stdout).strip()[:300] or "tailscale funnel failed"
        raise RuntimeError(detail)
    tcp = _run(
        ["tailscale", "serve", "--bg", f"--tcp={ssh_port}", f"tcp://127.0.0.1:{ssh_port}"],
        timeout=60,
    )
    if tcp.returncode != 0:
        detail = (tcp.stderr or tcp.stdout).strip()[:300] or "tailscale serve failed"
        raise RuntimeError(detail)
    url = funnel_url()
    host = urlparse(url).hostname or ""
    return {"ui_url": url, "ssh_host": host, "ssh_port": str(ssh_port)}


def apply_funnel_env(result: dict[str, str]) -> dict[str, str]:
    updates: dict[str, str] = {}
    if result.get("ui_url"):
        updates["PUBLIC_BASE_URL"] = result["ui_url"].rstrip("/")
        origins = [item.strip() for item in os.environ.get("ALLOWED_ORIGINS", "").split(",") if item.strip()]
        if result["ui_url"] not in origins:
            origins.append(result["ui_url"])
        updates["ALLOWED_ORIGINS"] = ",".join(origins)
        updates["COOKIE_SECURE"] = "true"
    if result.get("ssh_host"):
        os.environ["OPENGPU_SSH_HOST"] = result["ssh_host"]
        os.environ["OPENGPU_SSH_PORT"] = result.get("ssh_port") or str(settings.ssh_public_port)
    return updates
