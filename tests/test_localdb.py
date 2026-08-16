import localdb


def test_database_url_quotes_password():
    url = localdb.database_url("p@ss/word", 5433)
    assert url == "postgresql://opengpu:p%40ss%2Fword@127.0.0.1:5433/opengpu"


def test_compose_missing_docker(monkeypatch):
    monkeypatch.setattr(localdb.shutil, "which", lambda _name: None)
    assert localdb._compose_command() is None


def test_ensure_local_postgres_reports_compose_tail(monkeypatch, tmp_path):
    monkeypatch.setattr(localdb, "_compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(localdb, "postgres_path", lambda name: tmp_path / name)
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    monkeypatch.setattr(localdb, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(localdb, "_port_open", lambda _port: False)

    def fake_run(command, capture_output=True, text=True, check=False):
        assert command[:2] == ["docker", "compose"]
        assert command[2:4] == ["--progress", "plain"]
        stdout = "Image postgres:16 Pulling\n" + ("layer complete\n" * 40)
        stderr = "failed to extract layer: operation not permitted\n"
        return type("R", (), {"returncode": 1, "stdout": stdout, "stderr": stderr})()

    monkeypatch.setattr(localdb.subprocess, "run", fake_run)
    try:
        localdb.ensure_local_postgres()
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected compose failure")
    assert "operation not permitted" in message
