import argparse
import json

import docker

from database import get_connection
from manager import APP_LABEL, get_client
from security import normalize_email


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
                """INSERT INTO teams(id,name,email,display_name,enabled,provisioning_state)
                   VALUES (%s,%s,%s,%s,TRUE,'unprovisioned')""",
                (user_id, f"gpu{user_id}", normalize_email(args.email), args.display_name),
            )
            record(cursor, "whitelist", user_id)
        conn.commit()
        print(f"Whitelisted user {user_id} as gpu{user_id}")
    finally:
        conn.close()


def set_enabled(args, enabled):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE teams SET enabled=%s,provisioning_state=CASE
                   WHEN %s=FALSE THEN 'disabled'
                   WHEN container_name IS NULL THEN 'unprovisioned' ELSE 'ready' END
                   WHERE email=%s RETURNING id""",
                (enabled, enabled, normalize_email(args.email)),
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
            cursor.execute("SELECT id,email,name,enabled,provisioning_state,ssh_port FROM teams ORDER BY id")
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
            cursor.execute("SELECT id FROM teams WHERE email=%s AND enabled", (normalize_email(args.email),))
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
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id,container_name,volume_name FROM teams WHERE email=%s", (normalize_email(args.email),))
            row = cursor.fetchone()
            if not row:
                raise SystemExit("User not found")
        if row[1]:
            try:
                container = get_client().containers.get(row[1])
                if container.labels.get("app") != APP_LABEL:
                    mounts = {mount.get("Name") for mount in container.attrs.get("Mounts", [])}
                    if not args.legacy or row[2] not in mounts:
                        raise SystemExit(
                            "Refusing to replace an unmanaged container; "
                            "use --legacy only for a verified migrated user"
                        )
                if container.status == "running":
                    raise SystemExit("End/cancel the active reservation before rotating the password")
                container.remove()
            except docker.errors.NotFound:
                pass
        args.email = normalize_email(args.email)
        retry(args)
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
    p = commands.add_parser("rotate-password"); p.add_argument("email"); p.add_argument("--legacy", action="store_true"); p.set_defaults(func=rotate)
    return root


if __name__ == "__main__":
    args = parser().parse_args()
    args.func(args)
