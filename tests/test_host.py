from dataclasses import replace

import host
from host import Check


def test_configuration_reports_missing_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(host, "settings", replace(host.settings, cookie_secure=False))
    check = host.check_configuration()
    assert check.ok is False
    assert "DATABASE_URL" in check.detail


def test_docker_missing_from_path(monkeypatch):
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    check = host.check_docker()
    assert check.ok is False
    assert "PATH" in check.detail


def test_nvidia_requires_toolkit(monkeypatch):
    monkeypatch.setattr(
        host.shutil,
        "which",
        lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None,
    )
    monkeypatch.setattr(
        host,
        "_run",
        lambda command, timeout=15: type("R", (), {"returncode": 0, "stdout": "GPU 0: Test", "stderr": ""})(),
    )
    check = host.check_nvidia()
    assert check.ok is False
    assert "Container Toolkit" in check.detail


def test_storage_helper_points_at_init_host(tmp_path, monkeypatch):
    helper = tmp_path / "missing"
    monkeypatch.setattr(host, "settings", replace(host.settings, storage_helper=str(helper)))
    check = host.check_storage_helper()
    assert check.ok is False
    assert "setup" in check.detail


def test_init_host_runs_installer_with_sudo(tmp_path, monkeypatch):
    installer = tmp_path / "install-storage-helper"
    installer.write_text("#!/bin/sh\n")
    monkeypatch.setattr(host, "script_path", lambda *_parts: installer)
    monkeypatch.setattr(host, "settings", replace(host.settings, workspace_root=str(tmp_path / "ws")))
    captured = {}

    def fake_run(command, env=None, check=False):
        captured["command"] = command
        captured["env"] = env
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(host.subprocess, "run", fake_run)
    assert host.init_host() == 0
    assert captured["command"] == ["sudo", str(installer)]
    assert captured["env"]["WORKSPACE_ROOT"] == str(tmp_path / "ws")


def test_init_host_missing_installer(monkeypatch, tmp_path):
    monkeypatch.setattr(host, "script_path", lambda *_parts: tmp_path / "nope")
    assert host.init_host() == 1


def test_format_report_marks_warnings():
    report = host.format_report(
        [
            Check("docker", True, "ok"),
            Check("workspace", False, "low disk", fatal=False),
            Check("nvidia", False, "missing driver"),
        ]
    )
    assert "ok    docker:" in report
    assert "warn  workspace:" in report
    assert "fail  nvidia:" in report


def test_doctor_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(
        host,
        "collect_checks",
        lambda: [Check("docker", False, "no docker")],
    )
    assert host.doctor() == 1
    out = capsys.readouterr()
    assert "fail  docker:" in out.out
