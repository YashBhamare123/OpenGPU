from dataclasses import replace

import gateway
import host


def test_image_missing(monkeypatch):
    monkeypatch.setattr(host.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(host, "settings", replace(host.settings, docker_image="yashbhamare123/opengpu:ml"))

    def fake_run(command, timeout=15):
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "denied"})()

    monkeypatch.setattr(host, "_run", fake_run)
    check = host.check_image()
    assert check.ok is False
    assert "yashbhamare123/opengpu:ml" in check.detail


def test_image_pulls_when_missing(monkeypatch):
    monkeypatch.setattr(host.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(host, "settings", replace(host.settings, docker_image="yashbhamare123/opengpu:ml"))
    commands = []

    def fake_run(command, timeout=15):
        commands.append((command, timeout))
        if command[:3] == ["docker", "image", "inspect"]:
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "Digest: sha256:x", "stderr": ""})()

    monkeypatch.setattr(host, "_run", fake_run)
    check = host.ensure_image()
    assert check.ok is True
    assert commands[0][0][:3] == ["docker", "image", "inspect"]
    assert commands[1][0][:2] == ["docker", "pull"]
    assert commands[1][1] == 3600


def test_remote_access_warns_without_token(monkeypatch):
    monkeypatch.setattr("tunnel.ngrok_token", lambda: "")
    check = host.check_remote_access()
    assert check.ok is False
    assert check.fatal is False


def test_setup_skip_helper_stores_token(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("paths.ROOT", tmp_path)
    monkeypatch.setattr("tunnel.configure_agent", lambda _token: None)
    monkeypatch.setattr("tunnel.persist_token", lambda path, token: env_file.write_text(token))
    assert host.setup(token="secret-token", skip_helper=True, skip_image=True) == 0
    assert env_file.read_text() == "secret-token"


def test_active_ssh_backend_none(monkeypatch):
    class Conn:
        def cursor(self):
            return self

        def execute(self, _sql):
            return None

        def fetchone(self):
            return None

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(gateway, "get_connection", Conn)
    assert gateway.active_ssh_backend() is None
