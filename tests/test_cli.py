import pytest

import cli


def test_serve_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        cli.main(["serve", "--help"])
    assert exc.value.code == 0


def test_setup_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        cli.main(["setup", "--help"])
    assert exc.value.code == 0


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
    assert "{serve,setup,doctor,migrate,admin}" in out
    assert "init-host" not in out


def test_serve_defaults_to_no_tunnel(monkeypatch):
    captured = {}

    def fake_serve(*, host, port, tunnel):
        captured.update(host=host, port=port, tunnel=tunnel)

    monkeypatch.setattr("host.serve", fake_serve)
    cli.main(["serve", "--host", "127.0.0.1", "--port", "8000"])
    assert captured == {"host": "127.0.0.1", "port": 8000, "tunnel": False}
