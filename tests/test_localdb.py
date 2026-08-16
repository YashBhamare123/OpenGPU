import localdb


def test_database_url_quotes_password():
    url = localdb.database_url("p@ss/word", 5433)
    assert url == "postgresql://opengpu:p%40ss%2Fword@127.0.0.1:5433/opengpu"


def test_compose_missing_docker(monkeypatch):
    monkeypatch.setattr(localdb.shutil, "which", lambda _name: None)
    assert localdb._compose_command() is None
