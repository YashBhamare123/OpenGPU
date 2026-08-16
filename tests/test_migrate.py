from dataclasses import replace

import migrate


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class FakeConn:
    def __init__(self, *, teams=False, team_cols=(), reservation_cols=(), applied=()):
        self.teams = teams
        self.team_cols = set(team_cols)
        self.reservation_cols = set(reservation_cols)
        self.applied = set(applied)
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if "to_regclass" in sql:
            return FakeCursor([("teams",)] if self.teams else [(None,)])
        if "information_schema.columns" in sql:
            table = params[0] if params else ""
            cols = self.team_cols if table == "teams" else self.reservation_cols
            return FakeCursor([(name,) for name in sorted(cols)])
        if f"SELECT version FROM {migrate.SCHEMA_TABLE}" in sql:
            return FakeCursor([(version,) for version in sorted(self.applied)])
        if "INSERT INTO" in sql and migrate.SCHEMA_TABLE in sql:
            self.applied.add(params[0])
            return FakeCursor([])
        return FakeCursor([])

    def close(self):
        return None


CURRENT_TEAMS = {"ssh_password_hash", "provisioning_state", "volume_name"}
CURRENT_RESERVATIONS = {"duration_override", "workspace_gb", "temp_storage_gb"}


def test_upgrade_migrations_skip_down_files():
    names = [path.name for path in migrate.upgrade_migrations()]
    assert names == [
        "001_hardening.sql",
        "002_per_reservation_credentials.sql",
        "003_admin_duration_override.sql",
        "004_reservation_storage.sql",
        "005_configurable_duration_limit.sql",
    ]
    assert all(not name.endswith("_down.sql") for name in names)


def test_migrate_empty_database_applies_init_and_stamps(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(migrate, "_connect", lambda: conn)
    assert migrate.migrate() == 0
    assert any("btree_gist" in sql for sql in conn.statements)
    assert {path.name for path in migrate.upgrade_migrations()} <= conn.applied
    assert not any("ssh_password_legacy" in sql for sql in conn.statements)


def test_migrate_current_schema_stamps_without_running_upgrades(monkeypatch):
    conn = FakeConn(teams=True, team_cols=CURRENT_TEAMS, reservation_cols=CURRENT_RESERVATIONS)
    monkeypatch.setattr(migrate, "_connect", lambda: conn)
    assert migrate.migrate() == 0
    assert conn.applied == {path.name for path in migrate.upgrade_migrations()}
    assert not any("ALTER TABLE" in sql or "RENAME COLUMN" in sql for sql in conn.statements)


def test_migrate_legacy_schema_applies_pending_files(monkeypatch):
    conn = FakeConn(teams=True, team_cols={"email"}, reservation_cols={"start_time"})
    monkeypatch.setattr(migrate, "_connect", lambda: conn)
    assert migrate.migrate() == 0
    applied_sql = "\n".join(conn.statements)
    assert "ssh_password_legacy" in applied_sql
    assert conn.applied == {path.name for path in migrate.upgrade_migrations()}


def test_migrate_missing_database_url(monkeypatch):
    monkeypatch.setattr(migrate, "settings", replace(migrate.settings, database_url=""))
    assert migrate.migrate() == 1
