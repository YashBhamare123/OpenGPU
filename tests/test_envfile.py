import os

import envfile

REQUIRED = {
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


def _answer(prompt: str, *, empty_first: dict[str, int] | None = None) -> str:
    name = prompt.split()[0]
    empty_first = empty_first or {}
    if empty_first.get(name):
        empty_first[name] -= 1
        return ""
    field = next(item for item in envfile.FIELDS if item.name == name)
    if field.required:
        return REQUIRED[field.name]
    return "skip"


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
    chosen = envfile.configure_env(path, input_fn=_answer, getpass_fn=_answer)
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
    pending = {"ADMIN_EMAILS": 1}
    path = tmp_path / ".env"

    def fake(prompt):
        return _answer(prompt, empty_first=pending)

    chosen = envfile.configure_env(path, input_fn=fake, getpass_fn=fake)
    assert chosen["ADMIN_EMAILS"] == REQUIRED["ADMIN_EMAILS"]
    assert pending["ADMIN_EMAILS"] == 0


def test_default_env_path_uses_existing_cwd_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://x\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENGPU_ENV_FILE", raising=False)
    assert envfile.default_env_path() == env
