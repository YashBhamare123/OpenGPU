import json
import time

from config import settings
from database import get_connection
from manager import (
    managed_containers,
    provision_user,
    remove_container,
    start_container,
)

LOCK_ID = 72819431


def audit(cursor, event_type: str, team_id=None, details=None):
    cursor.execute(
        "INSERT INTO audit_events(team_id,event_type,details) VALUES (%s,%s,%s::jsonb)",
        (team_id, event_type, json.dumps(details or {})),
    )


def allocate_resources(cursor, team_id: int):
    cursor.execute("SELECT ssh_port,name,container_name,volume_name,legacy_volume FROM teams WHERE id=%s FOR UPDATE", (team_id,))
    port, username, container_name, volume_name, legacy_volume = cursor.fetchone()
    if port is None:
        cursor.execute("SELECT nextval('ssh_port_seq')")
        port = cursor.fetchone()[0]
        if port > settings.ssh_port_end:
            raise RuntimeError("SSH port range is exhausted")
    username = username or f"gpu{team_id}"
    container_name = container_name or f"gpu-user-{team_id}"
    volume_name = volume_name or f"gpu-workspace-{team_id}"
    cursor.execute(
        "UPDATE teams SET ssh_port=%s,name=%s,container_name=%s,volume_name=%s WHERE id=%s",
        (port, username, container_name, volume_name, team_id),
    )
    return port, username, container_name, volume_name, legacy_volume


def claim_job():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT j.id,j.team_id,t.email,j.purpose,
                  (SELECT r.start_time FROM reservations r
                   WHERE r.team_id=j.team_id AND NOT r.cancelled AND r.end_time>NOW()
                   ORDER BY r.start_time LIMIT 1),
                  (SELECT r.end_time FROM reservations r
                   WHERE r.team_id=j.team_id AND NOT r.cancelled AND r.end_time>NOW()
                   ORDER BY r.start_time LIMIT 1),
                  (SELECT r.workspace_gb FROM reservations r
                   WHERE r.team_id=j.team_id AND NOT r.cancelled AND r.end_time>NOW()
                   ORDER BY r.start_time LIMIT 1),
                  (SELECT r.temp_storage_gb FROM reservations r
                   WHERE r.team_id=j.team_id AND NOT r.cancelled AND r.end_time>NOW()
                   ORDER BY r.start_time LIMIT 1)
                FROM provisioning_jobs j
                JOIN teams t ON t.id=j.team_id
                WHERE j.state IN ('pending','failed') AND j.available_at<=NOW() AND t.enabled
                ORDER BY j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1
                """
            )
            job = cursor.fetchone()
            if not job:
                return None
            port, username, container_name, volume_name, legacy_volume = allocate_resources(cursor, job[1])
            cursor.execute(
                "UPDATE provisioning_jobs SET state='running',attempts=attempts+1,updated_at=NOW() WHERE id=%s",
                (job[0],),
            )
        conn.commit()
        return {"job_id": job[0], "user_id": job[1], "email": str(job[2]), "port": port,
                "username": username, "container_name": container_name, "volume_name": volume_name,
                "legacy_volume": legacy_volume, "purpose": job[3],
                "reservation_start": job[4], "reservation_end": job[5],
                "workspace_gb": job[6] or 2, "temp_storage_gb": job[7] or 100}
    finally:
        conn.close()


def process_one_job():
    job = claim_job()
    if not job:
        return
    try:
        password_hash = provision_user(
            job["user_id"], job["email"], job["username"], job["port"],
            job["container_name"], job["volume_name"], job["legacy_volume"],
            email_credentials=job["purpose"] != "initial",
            reservation_start=job["reservation_start"], reservation_end=job["reservation_end"],
            workspace_gb=job["workspace_gb"], temp_storage_gb=job["temp_storage_gb"],
        )
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE teams SET provisioning_state='ready',ssh_password_hash=%s,provisioning_error=NULL WHERE id=%s",
                    (password_hash, job["user_id"]),
                )
                cursor.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_name='teams' AND column_name='ssh_password_legacy'"
                )
                if cursor.fetchone():
                    cursor.execute("UPDATE teams SET ssh_password_legacy=NULL WHERE id=%s", (job["user_id"],))
                cursor.execute("UPDATE provisioning_jobs SET state='done',updated_at=NOW() WHERE id=%s", (job["job_id"],))
                audit(cursor, "provisioning_completed", job["user_id"], {"purpose": job["purpose"]})
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """UPDATE provisioning_jobs SET state='failed',last_error=%s,
                       available_at=NOW()+INTERVAL '1 minute',updated_at=NOW() WHERE id=%s""",
                    (str(exc)[:500], job["job_id"]),
                )
                cursor.execute(
                    "UPDATE teams SET provisioning_state='failed',provisioning_error=%s WHERE id=%s",
                    (str(exc)[:500], job["user_id"]),
                )
                audit(cursor, "provisioning_failed", job["user_id"], {"purpose": job["purpose"]})
            conn.commit()
        finally:
            conn.close()


def desired_container():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.id,t.container_name,r.workspace_gb,r.temp_storage_gb
                FROM reservations r JOIN teams t ON t.id=r.team_id
                WHERE r.start_time<=NOW() AND r.end_time>NOW() AND NOT r.cancelled
                  AND t.enabled AND t.provisioning_state='ready'
                ORDER BY r.start_time,r.id LIMIT 1
                """
            )
            return cursor.fetchone()
    finally:
        conn.close()


def retained_container_names():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT DISTINCT t.container_name
                   FROM reservations r JOIN teams t ON t.id=r.team_id
                   WHERE r.end_time>NOW() AND NOT r.cancelled AND t.enabled
                     AND t.container_name IS NOT NULL"""
            )
            return {row[0] for row in cursor}
    finally:
        conn.close()


def record_transition(event_type, team_id, container_name):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            audit(cursor, event_type, team_id, {"container": container_name})
        conn.commit()
    finally:
        conn.close()


def reconcile():
    desired = desired_container()
    retained = retained_container_names()
    containers = managed_containers()
    desired_name = desired[1] if desired else None
    for container in containers:
        if container.name not in retained:
            remove_container(container)
            record_transition("container_removed", int(container.labels["aiml.user_id"]), container.name)
        elif container.name != desired_name:
            container.reload()
            if container.status == "running":
                container.stop(timeout=15)
                record_transition("container_stopped", int(container.labels["aiml.user_id"]), container.name)
    if desired and not any(c.name == desired_name and c.status == "running" for c in containers):
        start_container(
            desired_name, desired[0],
            workspace_gb=desired[2] or 2, temp_storage_gb=desired[3] or 100,
        )
        record_transition("container_started", desired[0], desired_name)


def heartbeat(error=None):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO service_heartbeats(service_name,last_seen_at,details)
                   VALUES ('scheduler',NOW(),%s::jsonb)
                   ON CONFLICT(service_name) DO UPDATE SET last_seen_at=NOW(),details=EXCLUDED.details""",
                (json.dumps({"error": str(error)[:500] if error else None}),),
            )
        conn.commit()
    finally:
        conn.close()


def run():
    lock_conn = get_connection()
    lock_conn.autocommit = True
    with lock_conn.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
        if not cursor.fetchone()[0]:
            raise RuntimeError("Another scheduler already holds the control lock")
    while True:
        # If this dedicated connection dies, the leadership lock is gone;
        # exit rather than continuing as a second active scheduler.
        with lock_conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        error = None
        try:
            process_one_job()
            reconcile()
        except Exception as exc:  # noqa: BLE001
            error = exc
        try:
            heartbeat(error)
        except Exception:  # noqa: BLE001, S110
            pass
        time.sleep(settings.poll_interval)


if __name__ == "__main__":
    run()
