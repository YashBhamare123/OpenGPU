from __future__ import annotations

import getpass
import json
import os
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


def _current(field: EnvField, existing: dict[str, str]) -> str:
    return existing.get(field.name, os.environ.get(field.name, ""))


def _option_index(options: list[tuple[str, str, str]], value: str, fallback: int = 0) -> int:
    wanted = (value or "").strip().lower()
    for index, (item, _label, _detail) in enumerate(options):
        if item.lower() == wanted:
            return index
    return fallback


def _autofill(
    existing: dict[str, str],
    detected: dict[str, str],
    chosen: dict[str, str],
) -> None:
    for field in FIELDS:
        if field.name in chosen or field.prompt:
            continue
        current = _current(field, existing)
        if field.name == "ACCESS_CONTACT_EMAIL" and not current:
            current = chosen.get("ADMIN_EMAILS", "").split(",")[0].strip()
        fallback = _field_default(field, detected)
        if field.name == "COOKIE_SECURE" and chosen.get("ALLOWED_ORIGINS"):
            from detect import cookie_secure_for

            fallback = cookie_secure_for(chosen["ALLOWED_ORIGINS"])
        picked = current or fallback
        if picked:
            chosen[field.name] = picked
        elif field.required and not field.prompt:
            raise ValueError(f"{field.name} is required")


def _apply_supplied(
    existing: dict[str, str],
    detected: dict[str, str],
    values: dict[str, str],
) -> dict[str, str]:
    chosen: dict[str, str] = {}
    smtp_followups = {"SMTP_PORT", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD"}
    personal_skip = {
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_FROM",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "ADMIN_EMAILS",
        "ACCESS_CONTACT_EMAIL",
    }
    for field in FIELDS:
        if chosen.get("OPENGPU_MODE") == "personal" and field.name in personal_skip:
            continue
        if field.name in smtp_followups and not chosen.get("SMTP_HOST"):
            continue
        current = _current(field, existing)
        if field.name == "ACCESS_CONTACT_EMAIL" and not current:
            current = chosen.get("ADMIN_EMAILS", "").split(",")[0].strip()
        fallback = _field_default(field, detected)
        if field.name == "COOKIE_SECURE" and chosen.get("ALLOWED_ORIGINS"):
            from detect import cookie_secure_for

            fallback = cookie_secure_for(chosen["ALLOWED_ORIGINS"])
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
    return chosen


def _prompt_smtp(*, existing: dict[str, str], input_fn, getpass_fn) -> dict[str, str]:
    from ui import ask_choice, ask_text

    current_host = existing.get("SMTP_HOST") or os.environ.get("SMTP_HOST", "")
    action = ask_choice(
        "Lab email",
        "Login codes are emailed to allowlisted addresses. Skip SMTP to print admin codes on the host only.",
        [
            ("smtp", "Configure SMTP", "Gmail, Microsoft 365, or a campus relay"),
            ("skip", "Skip SMTP", "Admins can still sign in; codes print on this machine"),
        ],
        default=0 if current_host else 1,
        input_fn=input_fn,
    )
    if action == "skip":
        return {}
    provider = ask_choice(
        "SMTP provider",
        "OpenGPU sends mail with STARTTLS. App passwords are stored only in the local .env file.",
        [
            ("gmail", "Gmail", "smtp.gmail.com:587"),
            ("outlook", "Microsoft 365 / Outlook", "smtp.office365.com:587"),
            ("custom", "Custom relay", "You will enter the hostname"),
        ],
        default=_option_index(
            [("gmail", "", ""), ("outlook", "", ""), ("custom", "", "")],
            "gmail" if "gmail" in current_host else "outlook" if "office365" in current_host else "custom",
            2,
        ),
        input_fn=input_fn,
    )
    values: dict[str, str] = {}
    if provider == "gmail":
        values["SMTP_HOST"] = "smtp.gmail.com"
        values["SMTP_PORT"] = "587"
    elif provider == "outlook":
        values["SMTP_HOST"] = "smtp.office365.com"
        values["SMTP_PORT"] = "587"
    else:
        host = ask_text(
            "SMTP hostname",
            "Hostname of the STARTTLS relay.",
            default=current_host,
            required=True,
            input_fn=input_fn,
            getpass_fn=getpass_fn,
        )
        values["SMTP_HOST"] = host or current_host
        port = ask_text(
            "SMTP port",
            "Usually 587 for STARTTLS.",
            default=existing.get("SMTP_PORT") or os.environ.get("SMTP_PORT", "") or "587",
            required=True,
            input_fn=input_fn,
            getpass_fn=getpass_fn,
        )
        values["SMTP_PORT"] = port or "587"
    sender = ask_text(
        "From address",
        "Shown on login emails. Often the same as the SMTP username.",
        default=existing.get("SMTP_FROM") or os.environ.get("SMTP_FROM", ""),
        required=True,
        input_fn=input_fn,
        getpass_fn=getpass_fn,
    )
    values["SMTP_FROM"] = sender or ""
    user = ask_text(
        "SMTP username",
        "Leave blank if the relay does not require authentication.",
        default=existing.get("SMTP_USER") or os.environ.get("SMTP_USER", ""),
        required=False,
        input_fn=input_fn,
        getpass_fn=getpass_fn,
    )
    if user:
        values["SMTP_USER"] = user
    password = ask_text(
        "SMTP password",
        "App password or relay secret. Input is hidden.",
        default="",
        required=False,
        secret=True,
        input_fn=input_fn,
        getpass_fn=getpass_fn,
    )
    if password and not _is_skip(password):
        values["SMTP_PASSWORD"] = password
    return values


def _prompt_wizard(
    existing: dict[str, str],
    detected: dict[str, str],
    *,
    input_fn,
    getpass_fn,
) -> dict[str, str]:
    from detect import cookie_secure_for, nvidia_available
    from ui import ask_choice, ask_text

    chosen: dict[str, str] = {}
    _autofill(existing, detected, chosen)
    mode_options = [
        ("lab", "Lab", "Institute email allowlist and one-time login codes"),
        ("personal", "Personal", "Claim links over Tailscale Funnel"),
    ]
    current_mode = existing.get("OPENGPU_MODE") or os.environ.get("OPENGPU_MODE", "") or "lab"
    chosen["OPENGPU_MODE"] = ask_choice(
        "Onboarding mode",
        "Same GPU scheduler either way. This only changes how people are admitted.",
        mode_options,
        default=_option_index(mode_options, current_mode),
        input_fn=input_fn,
    )
    if chosen["OPENGPU_MODE"] == "personal":
        for key in (
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_FROM",
            "SMTP_USER",
            "SMTP_PASSWORD",
            "ADMIN_EMAILS",
            "ACCESS_CONTACT_EMAIL",
        ):
            chosen.pop(key, None)
    else:
        smtp = _prompt_smtp(existing=existing, input_fn=input_fn, getpass_fn=getpass_fn)
        for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD"):
            chosen.pop(key, None)
        chosen.update(smtp)
        admins = ask_text(
            "Administrator emails",
            "Comma-separated. These addresses can manage users and receive host-printed login codes if SMTP is skipped.",
            default=existing.get("ADMIN_EMAILS") or os.environ.get("ADMIN_EMAILS", ""),
            required=True,
            input_fn=input_fn,
            getpass_fn=getpass_fn,
        )
        chosen["ADMIN_EMAILS"] = admins or ""
        first_admin = chosen["ADMIN_EMAILS"].split(",")[0].strip()
        current_contact = (
            existing.get("ACCESS_CONTACT_EMAIL") or os.environ.get("ACCESS_CONTACT_EMAIL", "") or first_admin
        )
        contact_choice = ask_choice(
            "Access-denied contact",
            "Shown when someone who is not on the allowlist tries to sign in.",
            [
                ("admin", f"Use {first_admin}", "First administrator email"),
                ("custom", "Different address", "You will type it next"),
            ],
            default=0 if current_contact == first_admin else 1,
            input_fn=input_fn,
        )
        if contact_choice == "custom":
            contact = ask_text(
                "Contact email",
                "Public address for access requests.",
                default=current_contact,
                required=True,
                input_fn=input_fn,
                getpass_fn=getpass_fn,
            )
            chosen["ACCESS_CONTACT_EMAIL"] = contact or first_admin
        else:
            chosen["ACCESS_CONTACT_EMAIL"] = first_admin
    origins = chosen.get("ALLOWED_ORIGINS") or detected.get("ALLOWED_ORIGINS") or ""
    cookie_default = chosen.get("COOKIE_SECURE") or cookie_secure_for(origins)
    if chosen["OPENGPU_MODE"] == "personal" and not (existing.get("COOKIE_SECURE") or os.environ.get("COOKIE_SECURE")):
        cookie_default = "true"
    cookie_options = [
        ("false", "HTTP", "Local browser access without TLS"),
        ("true", "HTTPS", "Tailscale Funnel, reverse proxy, or public HTTPS"),
    ]
    chosen["COOKIE_SECURE"] = ask_choice(
        "Browser cookies",
        "Use HTTPS whenever the UI is reached over TLS so session cookies stay Secure.",
        cookie_options,
        default=_option_index(cookie_options, cookie_default, 0),
        input_fn=input_fn,
    )
    gpu_options = [
        ("false", "NVIDIA GPU", "User containers request one GPU"),
        ("true", "CPU-only", "No GPU device; uses the CPU image"),
    ]
    gpu_default = "true" if chosen.get("CPU_ONLY") == "true" or not nvidia_available() else "false"
    chosen["CPU_ONLY"] = ask_choice(
        "Accelerator",
        "NVIDIA was detected." if nvidia_available() else "NVIDIA was not detected on this host.",
        gpu_options,
        default=_option_index(gpu_options, gpu_default),
        input_fn=input_fn,
    )
    return chosen


def prompt_env(
    existing: dict[str, str],
    *,
    values: dict[str, str] | None = None,
    input_fn=input,
    getpass_fn=getpass.getpass,
    detected: dict[str, str] | None = None,
) -> dict[str, str]:
    detected = dict(detected or {})
    if values is not None:
        return _apply_supplied(existing, detected, values)
    return _prompt_wizard(existing, detected, input_fn=input_fn, getpass_fn=getpass_fn)


def configure_env(
    path: Path,
    *,
    values: dict[str, str] | None = None,
    input_fn=input,
    getpass_fn=getpass.getpass,
    write: bool = True,
    detected: dict[str, str] | None = None,
) -> dict[str, str]:
    from detect import host_defaults

    existing = parse_env(path)
    extras = {key: value for key, value in existing.items() if key not in {field.name for field in FIELDS}}
    detected = dict(host_defaults() if detected is None else detected)
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
