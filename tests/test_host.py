from dataclasses import replace
from pathlib import Path

import host
from host import Check


def test_configuration_reports_missing_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(host, "settings", replace(host.settings, cookie_secure=False))
    check = host.check_configuration()
    assert check.ok is False
    assert "DATABASE_URL" in check.detail


def test_smtp_skipped_is_a_warning(monkeypatch):
    monkeypatch.setattr(host, "settings", replace(host.settings, smtp_host="", smtp_from=""))
    check = host.check_smtp()
    assert check.ok is False
    assert check.fatal is False
    assert "administrators" in check.detail


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
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
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


def test_workspace_uses_ancestor_when_unreadable(tmp_path, monkeypatch):
    root = tmp_path / "users"
    root.mkdir()
    monkeypatch.setattr(host, "settings", replace(host.settings, workspace_root=str(root)))

    def fake_statvfs(path):
        if Path(path) == root:
            raise PermissionError("[Errno 13] Permission denied")
        return type("U", (), {"f_bavail": 50 * 1024 ** 3 // 4096, "f_frsize": 4096})()

    monkeypatch.setattr(host.os, "statvfs", fake_statvfs)
    monkeypatch.setattr(host, "get_connection", lambda: (_ for _ in ()).throw(RuntimeError("no database")))
    check = host.check_workspace()
    assert check.ok is True
    assert "50 GB free" in check.detail
    assert str(tmp_path) in check.detail


def test_doctor_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(
        host,
        "collect_checks",
        lambda: [Check("docker", False, "no docker")],
    )
    assert host.doctor() == 1
    out = capsys.readouterr()
    assert "fail  docker:" in out.out
