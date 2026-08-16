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
