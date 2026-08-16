import re
import sys
from pathlib import Path

import psycopg

from config import settings
from paths import postgres_path

SCHEMA_TABLE = "schema_migrations"
_UPGRADE_NAME = re.compile(r"^(\d{3})_.+(?<!_down)\.sql$")


def upgrade_migrations() -> list[Path]:
    files = []
    for path in sorted(postgres_path("migrations").glob("*.sql")):
        if _UPGRADE_NAME.match(path.name):
            files.append(path)
    return files


def migration_version(path: Path) -> str:
    return path.name


def _connect():
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(
        settings.database_url,
        autocommit=True,
        cursor_factory=psycopg.ClientCursor,
    )


def _has_relation(conn, name: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s)", (f"public.{name}",)).fetchone()
    return bool(row and row[0])


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema='public' AND table_name=%s""",
        (table,),
    )
    return {row[0] for row in rows}


def _ensure_registry(conn) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA_TABLE} (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )"""
    )


def _applied(conn) -> set[str]:
    rows = conn.execute(f"SELECT version FROM {SCHEMA_TABLE}")
    return {row[0] for row in rows}


def _stamp(conn, version: str) -> None:
    conn.execute(
        f"INSERT INTO {SCHEMA_TABLE}(version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
        (version,),
    )


def _apply_sql(conn, path: Path) -> None:
    conn.execute(path.read_text(encoding="utf-8"))


def schema_matches_init(conn) -> bool:
    return {"ssh_password_hash", "provisioning_state", "volume_name"} <= _columns(conn, "teams") and {
        "duration_override",
        "workspace_gb",
        "temp_storage_gb",
    } <= _columns(conn, "reservations")


def migrate() -> int:
    try:
        conn = _connect()
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot connect to PostgreSQL: {exc}", file=sys.stderr)
        return 1
    try:
        _ensure_registry(conn)
        applied = _applied(conn)
        files = upgrade_migrations()
        if not _has_relation(conn, "teams"):
            print("Empty database: applying postgres/init.sql")
            _apply_sql(conn, postgres_path("init.sql"))
            for path in files:
                _stamp(conn, migration_version(path))
            print(f"Stamped {len(files)} migrations as applied.")
            return 0
        if schema_matches_init(conn):
            missing = [path for path in files if migration_version(path) not in applied]
            for path in missing:
                _stamp(conn, migration_version(path))
            if missing:
                print(f"Schema already current; recorded {len(missing)} existing migrations.")
            else:
                print("Schema is already up to date.")
            return 0
        pending = [path for path in files if migration_version(path) not in applied]
        if not pending:
            print("Schema is already up to date.")
            return 0
        for path in pending:
            print(f"Applying {path.name}")
            _apply_sql(conn, path)
            _stamp(conn, migration_version(path))
        print(f"Applied {len(pending)} migration(s).")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
