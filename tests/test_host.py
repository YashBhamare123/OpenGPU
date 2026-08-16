import os
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


def test_nvidia_cpu_only_skips_driver(monkeypatch):
    monkeypatch.setenv("CPU_ONLY", "true")
    check = host.check_nvidia()
    assert check.ok is True
    assert "CPU-only" in check.detail


def test_doctor_prompts_for_cpu_only(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://x\nDOCKER_IMAGE=yashbhamare123/opengpu:ml\n")
    monkeypatch.setenv("OPENGPU_ENV_FILE", str(env))
    monkeypatch.setenv("CPU_ONLY", "false")
    monkeypatch.setenv("DOCKER_IMAGE", "yashbhamare123/opengpu:ml")
    monkeypatch.setattr(host.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(host.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        host,
        "collect_checks",
        lambda: [Check("docker", True, "ok"), Check("nvidia", True, "CPU-only")],
    )
    assert host.doctor(input_fn=lambda _prompt: "y") == 0
    assert os.environ["CPU_ONLY"] == "true"
    text = env.read_text()
    assert "CPU_ONLY=true" in text
    assert "opengpu:cpu" in text


def test_doctor_cpu_flag_skips_prompt(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://x\n")
    monkeypatch.setenv("OPENGPU_ENV_FILE", str(env))
    monkeypatch.setenv("CPU_ONLY", "false")
    monkeypatch.setenv("DOCKER_IMAGE", "yashbhamare123/opengpu:ml")
    monkeypatch.setattr(
        host,
        "collect_checks",
        lambda: [Check("nvidia", True, "CPU-only")],
    )
    assert host.doctor(cpu=True, input_fn=lambda _prompt: (_ for _ in ()).throw(AssertionError("prompted"))) == 0
    assert os.environ["CPU_ONLY"] == "true"


def test_doctor_noninteractive_nvidia_failure(monkeypatch):
    monkeypatch.setenv("CPU_ONLY", "false")
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    monkeypatch.setattr(host.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(host.sys.stdout, "isatty", lambda: False)
    assert host.doctor(input_fn=lambda _prompt: (_ for _ in ()).throw(AssertionError("prompted"))) == 1


def test_ensure_image_prefers_local_cpu_tag(monkeypatch):
    monkeypatch.setenv("CPU_ONLY", "true")
    monkeypatch.setenv("DOCKER_IMAGE", "yashbhamare123/opengpu:cpu")
    monkeypatch.setattr(host.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(host, "_persist_env_updates", lambda _updates: None)

    def fake_run(command, timeout=15):
        if command[:3] == ["docker", "image", "inspect"] and command[-1] == "opengpu:cpu":
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(host, "_run", fake_run)
    check = host.ensure_image()
    assert check.ok is True
    assert check.detail == "opengpu:cpu"
    assert os.environ["DOCKER_IMAGE"] == "opengpu:cpu"


def test_doctor_exit_code(monkeypatch, capsys):
    monkeypatch.setenv("CPU_ONLY", "true")
    monkeypatch.setattr(
        host,
        "collect_checks",
        lambda: [Check("docker", False, "no docker")],
    )
    assert host.doctor() == 1
    out = capsys.readouterr()
    assert "fail  docker:" in out.out
