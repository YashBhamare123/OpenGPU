from pathlib import Path

import detect


def test_container_cpus_caps_to_host(monkeypatch):
    monkeypatch.setattr(detect, "cpu_count", lambda: 4)
    assert detect.container_cpus() == 4
    assert detect.container_cpus(32) == 16
    assert detect.container_cpus(1) == 1


def test_container_memory_leaves_headroom():
    assert detect.container_memory_gb(16) == 14
    assert detect.container_memory_gb(4) == 2
    assert detect.container_memory_gb(2) == 1
    assert detect.container_shm(4) == "1g"


def test_cookie_secure_requires_all_https():
    assert detect.cookie_secure_for("https://gpu.example.edu") == "true"
    assert detect.cookie_secure_for("http://127.0.0.1:8000,https://gpu.example.edu") == "false"
    assert detect.cookie_secure_for("http://127.0.0.1:8000,http://localhost:8000") == "false"


def test_allowed_origins_include_loopback_and_optional_ngrok(monkeypatch):
    monkeypatch.setattr(detect, "routable_ipv4", lambda: "127.0.0.1")
    monkeypatch.delenv("NGROK_DOMAIN", raising=False)
    assert detect.allowed_origins(8000) == "http://127.0.0.1:8000,http://localhost:8000"
    monkeypatch.setenv("NGROK_DOMAIN", "example.ngrok-free.app")
    assert "https://example.ngrok-free.app" in detect.allowed_origins(8000)


def test_workspace_root_falls_back_when_docker_dir_unwritable(tmp_path, monkeypatch):
    monkeypatch.setattr(detect.Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.setattr(detect.os, "access", lambda _path, _mode: False)
    assert detect.workspace_root() == str(tmp_path / ".local/share/opengpu/workspaces")


def test_nvidia_missing_without_smi(monkeypatch):
    monkeypatch.setattr(detect.shutil, "which", lambda _name: None)
    assert detect.nvidia_available() is False


def test_host_defaults_cpu_only_without_nvidia(monkeypatch):
    monkeypatch.setattr(detect, "nvidia_available", lambda: False)
    monkeypatch.setattr(detect, "cpu_count", lambda: 4)
    monkeypatch.setattr(detect, "memory_gb", lambda: 8)
    monkeypatch.setattr(detect, "free_tcp_port", lambda start, host="127.0.0.1", span=20: start)
    monkeypatch.setattr(detect, "routable_ipv4", lambda: "10.0.0.5")
    monkeypatch.setattr(detect, "workspace_root", lambda: "/var/tmp/ws")
    monkeypatch.delenv("NGROK_DOMAIN", raising=False)
    values = detect.host_defaults()
    assert values["CPU_ONLY"] == "true"
    assert values["DOCKER_IMAGE"].endswith(":cpu")
    assert values["CONTAINER_CPUS"] == "4"
    assert values["CONTAINER_MEMORY"] == "6g"
    assert values["SERVER_IP"] == "10.0.0.5"
    assert values["COOKIE_SECURE"] == "false"
    assert "http://127.0.0.1:8000" in values["ALLOWED_ORIGINS"]
    assert "http://10.0.0.5:8000" in values["ALLOWED_ORIGINS"]
    assert detect.format_summary(values).startswith("Detected host defaults")
    assert Path("/var/tmp/ws").as_posix() == values["WORKSPACE_ROOT"]
