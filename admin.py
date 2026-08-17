import argparse
import json
from pathlib import Path

from database import get_connection
from security import (
    InvalidSshPublicKey,
    normalize_email,
    parse_ssh_public_key,
    ssh_key_public_view,
)


def record(cursor, event, user_id=None, details=None):
    cursor.execute(
        "INSERT INTO audit_events(team_id,event_type,details) VALUES (%s,%s,%s::jsonb)",
        (user_id, f"admin_{event}", json.dumps(details or {})),
    )


def whitelist(args):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT nextval(pg_get_serial_sequence('teams','id'))")
            user_id = cursor.fetchone()[0]
            cursor.execute(
                """INSERT INTO teams(id,name,email,handle,display_name,enabled,provisioning_state)
                   VALUES (%s,%s,%s,%s,%s,TRUE,'unprovisioned')""",
                (user_id, f"gpu{user_id}", normalize_email(args.email), f"gpu{user_id}", args.display_name),
            )
            record(cursor, "whitelist", user_id)
        conn.commit()
        print(f"Whitelisted user {user_id} as gpu{user_id}")
    finally:
        conn.close()


def _identity(value: str) -> tuple[str, str]:
    raw = value.strip()
    return normalize_email(raw) if "@" in raw else raw.casefold(), raw.casefold()


def set_enabled(args, enabled):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            email, handle = _identity(args.email)
            cursor.execute(
                """UPDATE teams SET enabled=%s,provisioning_state=CASE
                   WHEN %s=FALSE THEN 'disabled'
                   WHEN container_name IS NULL THEN 'unprovisioned' ELSE 'ready' END
                   WHERE email=%s OR handle=%s RETURNING id""",
                (enabled, enabled, email, handle),
            )
            row = cursor.fetchone()
            if not row:
                raise SystemExit("User not found")
            record(cursor, "enable" if enabled else "disable", row[0])
        conn.commit()
    finally:
        conn.close()


def list_users(_args):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id,email,name,enabled,provisioning_state,ssh_port,handle FROM teams ORDER BY id")
            for row in cursor:
                print(*row, sep="\t")
    finally:
        conn.close()


def cancel(args):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE reservations SET cancelled=TRUE,cancelled_at=NOW(),cancellation_reason=%s
                   WHERE id=%s AND NOT cancelled RETURNING team_id""",
                (args.reason, args.reservation_id),
            )
            row = cursor.fetchone()
            if not row:
                raise SystemExit("Reservation not found or already cancelled")
            record(cursor, "cancel", row[0], {"reservation_id": args.reservation_id, "reason": args.reason})
        conn.commit()
    finally:
        conn.close()


def retry(args):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            email, handle = _identity(args.email)
            cursor.execute(
                "SELECT id FROM teams WHERE (email=%s OR handle=%s) AND enabled",
                (email, handle),
            )
            row = cursor.fetchone()
            if not row:
                raise SystemExit("Enabled user not found")
            cursor.execute(
                """INSERT INTO provisioning_jobs(team_id,purpose) VALUES (%s,'admin')
                   ON CONFLICT(team_id) DO UPDATE SET state='pending',purpose='admin',available_at=NOW(),last_error=NULL,updated_at=NOW()""",
                (row[0],),
            )
            cursor.execute("UPDATE teams SET provisioning_state='pending',provisioning_error=NULL WHERE id=%s", (row[0],))
            record(cursor, "provision_retry", row[0])
        conn.commit()
    finally:
        conn.close()


def rotate(args):
    raise SystemExit("SSH passwords are no longer used. Set a public key with: opengpu admin set-ssh-key")


def _load_public_key(args) -> str:
    if args.file:
        return Path(args.file).read_text()
    if args.public_key:
        return args.public_key
    raise SystemExit("Provide a public key string or --file")


def set_ssh_key(args):
    try:
        canonical = parse_ssh_public_key(_load_public_key(args))
    except InvalidSshPublicKey as exc:
        raise SystemExit(str(exc)) from exc
    except OSError as exc:
        raise SystemExit(f"Unable to read key file: {exc}") from exc
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            email, handle = _identity(args.email)
            cursor.execute(
                "UPDATE teams SET ssh_public_key=%s WHERE email=%s OR handle=%s RETURNING id",
                (canonical, email, handle),
            )
            row = cursor.fetchone()
            if not row:
                raise SystemExit("User not found")
            view = ssh_key_public_view(canonical)
            record(cursor, "ssh_key_set", row[0], {"fingerprint": view["fingerprint"]})
        conn.commit()
        print(view["fingerprint"], view["comment"] or "", sep="\t")
    finally:
        conn.close()


def show_ssh_key(args):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            email, handle = _identity(args.email)
            cursor.execute(
                "SELECT ssh_public_key FROM teams WHERE email=%s OR handle=%s",
                (email, handle),
            )
            row = cursor.fetchone()
            if not row:
                raise SystemExit("User not found")
        view = ssh_key_public_view(row[0])
        if not view:
            print("none")
            return
        print(view["fingerprint"], view["comment"] or "", sep="\t")
    finally:
        conn.close()


def clear_ssh_key(args):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            email, handle = _identity(args.email)
            cursor.execute(
                "UPDATE teams SET ssh_public_key=NULL WHERE email=%s OR handle=%s RETURNING id",
                (email, handle),
            )
            row = cursor.fetchone()
            if not row:
                raise SystemExit("User not found")
            record(cursor, "ssh_key_cleared", row[0])
        conn.commit()
    finally:
        conn.close()


def parser():
    root = argparse.ArgumentParser(description="OpenGPU administration")
    commands = root.add_subparsers(required=True)
    p = commands.add_parser("whitelist"); p.add_argument("email"); p.add_argument("--display-name"); p.set_defaults(func=whitelist)
    for name, enabled in (("enable", True), ("disable", False)):
        p = commands.add_parser(name); p.add_argument("email"); p.set_defaults(func=lambda a, e=enabled: set_enabled(a, e))
    p = commands.add_parser("list-users"); p.set_defaults(func=list_users)
    p = commands.add_parser("cancel"); p.add_argument("reservation_id", type=int); p.add_argument("--reason", default="cancelled by admin"); p.set_defaults(func=cancel)
    p = commands.add_parser("retry-provision"); p.add_argument("email"); p.set_defaults(func=retry)
    p = commands.add_parser("set-ssh-key"); p.add_argument("email"); p.add_argument("public_key", nargs="?"); p.add_argument("--file"); p.set_defaults(func=set_ssh_key)
    p = commands.add_parser("show-ssh-key"); p.add_argument("email"); p.set_defaults(func=show_ssh_key)
    p = commands.add_parser("clear-ssh-key"); p.add_argument("email"); p.set_defaults(func=clear_ssh_key)
    return root


if __name__ == "__main__":
    args = parser().parse_args()
    args.func(args)
