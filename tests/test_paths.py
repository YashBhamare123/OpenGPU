from pathlib import Path

import paths


def test_asset_paths_do_not_depend_on_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Path(paths.__file__).resolve().parent == paths.ROOT
    assert paths.frontend_path("index.html").is_file()
    assert paths.frontend_path("admin.html").is_file()
    assert paths.postgres_path("init.sql").is_file()
    assert not (tmp_path / "frontend").exists()
    assert not (tmp_path / "postgres").exists()
