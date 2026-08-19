import os

import envfile

REQUIRED = {
    "OPENGPU_MODE": "lab",
    "SERVER_IP": "10.0.0.10",
    "DOCKER_BIND_IP": "10.0.0.10",
    "WORKSPACE_ROOT": "/var/tmp/opengpu-ws",
    "SMTP_HOST": "smtp.example.edu",
    "SMTP_PORT": "587",
    "SMTP_FROM": "gpu@example.edu",
    "ALLOWED_ORIGINS": "https://gpu.example.edu",
    "COOKIE_SECURE": "true",
    "ADMIN_EMAILS": "admin@example.edu",
}


def _preserve_env(monkeypatch):
    for field in envfile.FIELDS:
        if field.name in os.environ:
            monkeypatch.setenv(field.name, os.environ[field.name])
        else:
            monkeypatch.delenv(field.name, raising=False)
    monkeypatch.setenv("DOCKER_IMAGE", "yashbhamare123/opengpu:ml")
    monkeypatch.setenv("CPU_ONLY", "false")
    monkeypatch.setattr("detect.host_defaults", dict)
    monkeypatch.setattr("detect.nvidia_available", lambda: True)


def _replies(*answers):
    pending = list(answers)

    def fake(_prompt):
        if not pending:
            return ""
        return pending.pop(0)

    return fake


def test_write_env_skips_optional_and_hides_secrets(tmp_path, monkeypatch, capsys):
    _preserve_env(monkeypatch)
    path = tmp_path / "env"
    values = {**REQUIRED, "SMTP_PASSWORD": "skip", "NGROK_AUTHTOKEN": ""}
    chosen = envfile.configure_env(path, values=values)
    text = path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert "SMTP_PASSWORD=" not in text
    assert "NGROK_AUTHTOKEN=" not in text
    assert "DOCKER_IMAGE=yashbhamare123/opengpu:ml" in text
    assert chosen["ADMIN_EMAILS"] == "admin@example.edu"
    out = capsys.readouterr().out
    assert "SMTP_PASSWORD" not in out
    assert "NGROK_AUTHTOKEN" not in out


def test_prompt_skip_keeps_optional_empty(tmp_path, monkeypatch):
    _preserve_env(monkeypatch)
    for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "NGROK_AUTHTOKEN", "PUBLIC_BASE_URL", "ACCESS_CONTACT_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    chosen = envfile.configure_env(
        path,
        input_fn=_replies("1", "2", "admin@example.edu", "1", "1", "1"),
        getpass_fn=_replies(),
    )
    assert "SMTP_HOST" not in chosen
    assert "SMTP_USER" not in chosen
    assert "NGROK_AUTHTOKEN" not in chosen
    assert chosen["DOCKER_IMAGE"] == "yashbhamare123/opengpu:ml"
    assert "SMTP_PASSWORD=" not in path.read_text()


def test_skip_smtp_omits_relay_fields(tmp_path, monkeypatch):
    _preserve_env(monkeypatch)
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    values = {name: value for name, value in REQUIRED.items() if not name.startswith("SMTP_")}
    values["SMTP_HOST"] = "skip"
    chosen = envfile.configure_env(path, values=values)
    assert "SMTP_HOST" not in chosen
    assert "SMTP_FROM" not in chosen
    assert "SMTP_HOST=" not in path.read_text()


def test_required_reprompts_on_empty(tmp_path, monkeypatch):
    _preserve_env(monkeypatch)
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    path = tmp_path / ".env"
    chosen = envfile.configure_env(
        path,
        input_fn=_replies("1", "2", "", "admin@example.edu", "1", "1", "1"),
        getpass_fn=_replies(),
    )
    assert chosen["ADMIN_EMAILS"] == REQUIRED["ADMIN_EMAILS"]


def test_interactive_setup_pages_lab_identity(tmp_path, monkeypatch, capsys):
    _preserve_env(monkeypatch)
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    for key in ("SMTP_HOST", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD", "ACCESS_CONTACT_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    envfile.configure_env(
        tmp_path / ".env",
        input_fn=_replies("1", "2", "admin@example.edu", "1", "1", "1"),
        getpass_fn=_replies(),
    )
    out = capsys.readouterr().out
    assert "Onboarding mode" in out
    assert "Lab email" in out
    assert "Administrator emails" in out
    assert "Access-denied contact" in out
    assert "Browser cookies" in out
    assert "Accelerator" in out
    assert "SMTP provider" not in out


def test_personal_mode_skips_lab_email_pages(tmp_path, monkeypatch, capsys):
    _preserve_env(monkeypatch)
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    chosen = envfile.configure_env(
        tmp_path / ".env",
        input_fn=_replies("2", "2", "1"),
        getpass_fn=_replies(),
    )
    out = capsys.readouterr().out
    assert chosen["OPENGPU_MODE"] == "personal"
    assert "ADMIN_EMAILS" not in chosen
    assert "SMTP_HOST" not in chosen
    assert "Lab email" not in out
    assert "Administrator emails" not in out
    assert chosen["COOKIE_SECURE"] == "true"
    assert chosen["CLAIM_HOURS"] == "72"


def test_empty_prompt_accepts_detected_origins(tmp_path, monkeypatch):
    _preserve_env(monkeypatch)
    for key in ("ALLOWED_ORIGINS", "COOKIE_SECURE", "ADMIN_EMAILS"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    detected = {
        "ALLOWED_ORIGINS": "http://127.0.0.1:8000,http://localhost:8000",
        "COOKIE_SECURE": "false",
        "SERVER_IP": "127.0.0.1",
        "DOCKER_BIND_IP": "127.0.0.1",
        "WORKSPACE_ROOT": "/var/tmp/ws",
    }
    chosen = envfile.configure_env(
        path,
        input_fn=_replies("1", "2", "admin@example.edu", "1", "", "1"),
        getpass_fn=_replies(),
        detected=detected,
    )
    assert chosen["ALLOWED_ORIGINS"] == detected["ALLOWED_ORIGINS"]
    assert chosen["COOKIE_SECURE"] == "false"


def test_gmail_smtp_pages_fill_relay(tmp_path, monkeypatch):
    _preserve_env(monkeypatch)
    for key in ("SMTP_HOST", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD", "ADMIN_EMAILS"):
        monkeypatch.delenv(key, raising=False)
    chosen = envfile.configure_env(
        tmp_path / ".env",
        input_fn=_replies("1", "1", "1", "gpu@example.edu", "gpu@example.edu", "admin@example.edu", "1", "2", "1"),
        getpass_fn=_replies("app-password"),
    )
    assert chosen["SMTP_HOST"] == "smtp.gmail.com"
    assert chosen["SMTP_PORT"] == "587"
    assert chosen["SMTP_FROM"] == "gpu@example.edu"
    assert chosen["SMTP_USER"] == "gpu@example.edu"
    assert chosen["SMTP_PASSWORD"] == "app-password"
    assert chosen["COOKIE_SECURE"] == "true"


def test_default_env_path_uses_existing_cwd_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://x\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENGPU_ENV_FILE", raising=False)
    assert envfile.default_env_path() == env
