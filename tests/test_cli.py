from pathlib import Path

import pytest

import cli


def test_serve_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        cli.main(["serve", "--help"])
    assert exc.value.code == 0


def test_setup_help_mentions_skip_env(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["setup", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--skip-env" in out
    assert "--skip-postgres" in out
    assert "--env-file" in out


def test_init_host_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        cli.main(["init-host", "--help"])
    assert exc.value.code == 0


def test_migrate_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        cli.main(["migrate", "--help"])
    assert exc.value.code == 0


def test_help_hides_internal_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "==SUPPRESS==" not in out
    assert "{serve,setup,doctor,migrate,share,reserve,revoke,admin}" in out
    assert "init-host" not in out
    assert "  api" not in out


def test_share_help_mentions_handle(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["share", "--help"])
    assert exc.value.code == 0
    assert "handle" in capsys.readouterr().out.lower()


def test_serve_defaults_to_no_tunnel(monkeypatch):
    captured = {}

    def fake_serve(*, host, port, tunnel, scheduler=True, pull_image=True):
        captured.update(host=host, port=port, tunnel=tunnel, scheduler=scheduler, pull_image=pull_image)

    monkeypatch.setattr("host.serve", fake_serve)
    cli.main(["serve", "--host", "127.0.0.1", "--port", "8000"])
    assert captured == {
        "host": "127.0.0.1",
        "port": 8000,
        "tunnel": False,
        "scheduler": True,
        "pull_image": True,
    }


def test_api_skips_scheduler_and_image_pull(monkeypatch):
    captured = {}

    def fake_serve(*, host, port, tunnel, scheduler=True, pull_image=True):
        captured.update(host=host, port=port, tunnel=tunnel, scheduler=scheduler, pull_image=pull_image)

    monkeypatch.setattr("host.serve", fake_serve)
    cli.main(["api", "--host", "127.0.0.1", "--port", "9473"])
    assert captured == {
        "host": "127.0.0.1",
        "port": 9473,
        "tunnel": False,
        "scheduler": False,
        "pull_image": False,
    }


def test_production_api_unit_does_not_start_combined_serve():
    text = Path("deploy/aiml-gpu-api.service").read_text(encoding="utf-8")
    exec_start = next(line for line in text.splitlines() if line.startswith("ExecStart="))
    assert exec_start.endswith("opengpu api --host 127.0.0.1 --port 9473")
    assert "opengpu serve" not in exec_start
    scheduler = Path("deploy/aiml-gpu-scheduler.service").read_text(encoding="utf-8")
    assert "opengpu scheduler" in scheduler
