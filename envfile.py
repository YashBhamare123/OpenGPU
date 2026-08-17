from __future__ import annotations

import getpass
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from paths import ROOT

SKIP_ANSWERS = {"", "skip", "none", "-"}


@dataclass(frozen=True)
class EnvField:
    name: str
    help: str
    required: bool = False
    secret: bool = False
    default: str = ""
    prompt: bool = False


FIELDS: tuple[EnvField, ...] = (
    EnvField("OPENGPU_MODE", "lab (OTP allowlist) or personal (Tailscale claim links)", required=True, prompt=True, default="lab"),
    EnvField("SERVER_IP", "Address advertised in the SSH command", required=True, default="127.0.0.1"),
    EnvField("DOCKER_BIND_IP", "Host interface Docker publishes SSH on", required=True, default="127.0.0.1"),
    EnvField("WORKSPACE_ROOT", "Directory for workspace and scratch images", required=True, default="/var/lib/docker/opengpu-workspaces"),
    EnvField("SMTP_HOST", "SMTP relay hostname; skip in Personal mode", prompt=True),
    EnvField("SMTP_PORT", "SMTP port", default="587"),
    EnvField("SMTP_FROM", "From address for login and SSH emails", prompt=True),
    EnvField("ALLOWED_ORIGINS", "Comma-separated browser origins", required=True, default="http://127.0.0.1:9473,http://localhost:9473"),
    EnvField("COOKIE_SECURE", "true when serving over HTTPS", required=True, default="false"),
    EnvField("ADMIN_EMAILS", "Comma-separated admin emails", required=True, prompt=True),
    EnvField("SMTP_USER", "SMTP username", prompt=True),
    EnvField("SMTP_PASSWORD", "SMTP password", secret=True, prompt=True),
    EnvField("PUBLIC_BASE_URL", "Public site URL"),
    EnvField("ACCESS_CONTACT_EMAIL", "Contact shown when access is denied", prompt=True),
    EnvField("DOCKER_IMAGE", "User container image", default="yashbhamare123/opengpu:ml"),
    EnvField("CPU_ONLY", "true to run user containers without a GPU", default="false"),
    EnvField("STORAGE_HELPER", "Installed storage helper path", default="/usr/local/sbin/opengpu-storage-init"),
    EnvField("SSH_PUBLIC_PORT", "Local SSH gateway port", default="9474"),
    EnvField("SSH_GATEWAY_BIND", "SSH gateway bind address", default="127.0.0.1"),
    EnvField("SSH_PORT_START", "First published container SSH port", default="22001"),
    EnvField("SSH_PORT_END", "Last published container SSH port", default="32000"),
    EnvField("API_HOST", "API listen address", default="127.0.0.1"),
    EnvField("API_PORT", "API listen port", default="9473"),
    EnvField("SESSION_HOURS", "Browser session length", default="12"),
    EnvField("OTP_MINUTES", "Login code lifetime", default="10"),
    EnvField("OTP_MAX_ATTEMPTS", "Login code attempts", default="5"),
    EnvField("RESERVATION_LIMIT_MINUTES", "Standard reservation length", default="120"),
    EnvField("POLL_INTERVAL", "Scheduler poll seconds", default="5"),
    EnvField("CONTAINER_MEMORY", "Container memory limit", default="32g"),
    EnvField("CONTAINER_CPUS", "Container CPU count", default="16"),
    EnvField("CONTAINER_PIDS", "Container PID limit", default="4096"),
    EnvField("CONTAINER_SHM", "Container /dev/shm size", default="16g"),
    EnvField("NGROK_AUTHTOKEN", "Remote SSH tunnel token (NGROK_TOKEN is also accepted)", secret=True),
    EnvField("NGROK_TCP_ADDR", "Reserved ngrok TCP address"),
    EnvField("NGROK_DOMAIN", "Fixed ngrok HTTPS hostname for the web UI"),
)


def default_env_path() -> Path:
    specified = os.environ.get("OPENGPU_ENV_FILE", "").strip()
    if specified:
        return Path(specified).expanduser()
    candidates = (
        Path.cwd() / ".env",
        ROOT / ".env",
        Path.home() / ".config/opengpu/env",
    )
    for path in candidates:
        if path.is_file():
            return path
    if "site-packages" in Path(ROOT).parts:
        return Path.home() / ".config/opengpu/env"
    return Path.cwd() / ".env"


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value
    return values


def _quote(value: str) -> str:
    if value and not any(ch in value for ch in ' \t\n#"\''):
        return value
    return json.dumps(value)


def write_env(path: Path, values: dict[str, str], extras: dict[str, str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    written: set[str] = set()
    for field in FIELDS:
        if field.name not in values:
            continue
        lines.append(f"# {field.help}")
        lines.append(f"{field.name}={_quote(values[field.name])}")
        written.add(field.name)
    for key, value in values.items():
        if key in written:
            continue
        if key == "DATABASE_URL":
            lines.append("# PostgreSQL URL from local Docker Compose")
        lines.append(f"{key}={_quote(value)}")
        written.add(key)
    for key, value in (extras or {}).items():
        if key in written:
            continue
        lines.append(f"{key}={_quote(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def apply_env(values: dict[str, str]) -> None:
    for key, value in values.items():
        os.environ[key] = value


def _is_skip(answer: str) -> bool:
    return answer.strip().lower() in SKIP_ANSWERS


def _field_default(field: EnvField, detected: dict[str, str]) -> str:
    return detected.get(field.name) or field.default


def _prompt_one(field: EnvField, current: str, *, input_fn, getpass_fn, detected: dict[str, str]) -> str | None:
    shown = current or _field_default(field, detected)
    if field.required:
        hint = f" [{shown}]" if shown else " [required]"
    else:
        hint = f" [{shown}, skip to keep]" if shown else " [skip]"
    prompt = f"{field.name} ({field.help}){hint}: "
    if field.secret:
        answer = getpass_fn(prompt)
    else:
        answer = input_fn(prompt)
    answer = "" if answer is None else str(answer).strip()
    if field.required:
        if answer:
            return answer
        if shown:
            return shown
        return None
    if _is_skip(answer):
        return shown or None
    return answer


def prompt_env(
    existing: dict[str, str],
    *,
    values: dict[str, str] | None = None,
    input_fn=input,
    getpass_fn=getpass.getpass,
    detected: dict[str, str] | None = None,
) -> dict[str, str]:
    detected = dict(detected or {})
    chosen: dict[str, str] = {}
    smtp_followups = {"SMTP_PORT", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD"}
    personal_skip = {"SMTP_HOST", "SMTP_PORT", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD", "ADMIN_EMAILS", "ACCESS_CONTACT_EMAIL"}
    for field in FIELDS:
        if chosen.get("OPENGPU_MODE") == "personal" and field.name in personal_skip:
            continue
        if field.name in smtp_followups and not chosen.get("SMTP_HOST"):
            continue
        current = existing.get(field.name, os.environ.get(field.name, ""))
        if field.name == "ACCESS_CONTACT_EMAIL" and not current:
            current = chosen.get("ADMIN_EMAILS", "").split(",")[0].strip()
        fallback = _field_default(field, detected)
        if field.name == "COOKIE_SECURE" and chosen.get("ALLOWED_ORIGINS"):
            from detect import cookie_secure_for

            fallback = cookie_secure_for(chosen["ALLOWED_ORIGINS"])
        if values is not None:
            if field.name in values:
                raw = values[field.name]
                if field.required:
                    chosen[field.name] = raw or fallback
                elif not _is_skip(raw):
                    chosen[field.name] = raw
                elif fallback:
                    chosen[field.name] = fallback
                continue
            if field.required:
                chosen[field.name] = current or fallback
            elif current:
                chosen[field.name] = current
            elif fallback:
                chosen[field.name] = fallback
            continue
        if not field.prompt:
            picked = current or fallback
            if picked:
                chosen[field.name] = picked
            elif field.required:
                raise ValueError(f"{field.name} is required")
            continue
        while True:
            picked = _prompt_one(field, current, input_fn=input_fn, getpass_fn=getpass_fn, detected=detected)
            if picked is None and field.required:
                print(f"{field.name} is required.", file=sys.stderr)
                continue
            if picked is not None:
                chosen[field.name] = picked
            break
    return chosen


def configure_env(
    path: Path,
    *,
    values: dict[str, str] | None = None,
    input_fn=input,
    getpass_fn=getpass.getpass,
    write: bool = True,
    detected: dict[str, str] | None = None,
) -> dict[str, str]:
    from detect import format_summary, host_defaults

    existing = parse_env(path)
    extras = {key: value for key, value in existing.items() if key not in {field.name for field in FIELDS}}
    detected = dict(host_defaults() if detected is None else detected)
    if values is None and sys.stdin.isatty() and sys.stdout.isatty():
        print(format_summary(detected), flush=True)
    chosen = prompt_env(
        existing, values=values, input_fn=input_fn, getpass_fn=getpass_fn, detected=detected
    )
    missing = [field.name for field in FIELDS if field.required and not chosen.get(field.name)]
    if chosen.get("OPENGPU_MODE") == "personal":
        missing = [name for name in missing if name != "ADMIN_EMAILS"]
    if missing:
        raise ValueError("missing required settings: " + ", ".join(missing))
    if write:
        write_env(path, chosen, extras)
        apply_env(chosen)
        os.environ["OPENGPU_ENV_FILE"] = str(path)
    return chosen
