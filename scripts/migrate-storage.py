#!/usr/bin/env python3
"""Copy legacy Docker storage volumes into transparent host directories.

Run with the scheduler stopped. Source volumes are retained as rollback copies.
"""

import json
import sys
from pathlib import Path

import docker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from database import get_connection
from manager import APP_LABEL, get_client, prepare_user_storage, storage_destination_has_user_files


def source_volume(name: str, user_id: int, allow_unlabelled: bool = False):
    try:
        volume = get_client().volumes.get(name)
    except docker.errors.NotFound:
        return None
    labels = volume.attrs.get("Labels") or {}
    owned = labels.get("app") == APP_LABEL and labels.get("aiml.user_id") == str(user_id)
    if not owned and not (allow_unlabelled and not labels):
        raise RuntimeError(f"Refusing unowned volume {name}")
    return volume


def copy_volume(name: str, destination: Path) -> bool:
    if storage_destination_has_user_files(destination):
        raise RuntimeError(f"Destination is not empty: {destination}")
    container = get_client().containers.create(
        image=settings.docker_image,
        entrypoint="/bin/bash",
        command=["-c", "cp -a /source/. /destination/"],
        volumes={
            name: {"bind": "/source", "mode": "ro"},
            str(destination): {"bind": "/destination", "mode": "rw"},
        },
        labels={"app": "aiml-storage-migration"},
    )
    try:
        container.start()
        result = container.wait(timeout=300)
        if result["StatusCode"] != 0:
            logs = container.logs().decode("utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"Copy from {name} failed: {logs}")
    finally:
        container.remove(force=True)
    return True


def main() -> None:
    with get_connection() as connection:
        teams = connection.execute(
            """SELECT t.id,t.container_name,t.volume_name,t.legacy_volume,
                      (SELECT r.workspace_gb FROM reservations r
                       WHERE r.team_id=t.id AND NOT r.cancelled AND r.end_time>NOW()
                       ORDER BY r.start_time LIMIT 1),
                      (SELECT r.temp_storage_gb FROM reservations r
                       WHERE r.team_id=t.id AND NOT r.cancelled AND r.end_time>NOW()
                       ORDER BY r.start_time LIMIT 1)
               FROM teams t ORDER BY t.id"""
        ).fetchall()

    for user_id, container_name, workspace_volume, legacy_volume, workspace_gb, temp_storage_gb in teams:
        existing_container = None
        if container_name:
            try:
                existing_container = get_client().containers.get(container_name)
                existing_container.reload()
                if existing_container.labels.get("app") != APP_LABEL:
                    raise RuntimeError(f"Refusing unmanaged container {container_name}")
                if existing_container.status == "running":
                    raise RuntimeError(f"Stop {container_name} before migrating user {user_id}")
            except docker.errors.NotFound:
                existing_container = None

        host_key_volume = f"gpu-hostkeys-{user_id}"
        will_copy = bool(
            (workspace_volume and source_volume(workspace_volume, user_id, legacy_volume))
            or source_volume(host_key_volume, user_id)
        )
        if not will_copy:
            print(f"user {user_id}: no legacy volumes")
            continue
        if existing_container is not None:
            existing_container.remove()

        workspace, host_keys, _scratch_home, _scratch_tmp, _scratch_etc = prepare_user_storage(
            user_id, workspace_gb or 2, temp_storage_gb or 100, convert=True,
        )
        copied = []
        if workspace_volume and source_volume(workspace_volume, user_id, legacy_volume):
            copy_volume(workspace_volume, workspace)
            copied.append(workspace_volume)
        if source_volume(host_key_volume, user_id):
            copy_volume(host_key_volume, host_keys)
            copied.append(host_key_volume)

        if copied:
            with get_connection() as connection:
                reservation = connection.execute(
                    """SELECT id FROM reservations
                       WHERE team_id=%s AND end_time>NOW() AND NOT cancelled
                       ORDER BY start_time LIMIT 1""",
                    (user_id,),
                ).fetchone()
                if reservation:
                    connection.execute(
                        """INSERT INTO provisioning_jobs(team_id,purpose,state,attempts,available_at,last_error,updated_at)
                           VALUES (%s,'reservation','pending',0,NOW(),NULL,NOW())
                           ON CONFLICT(team_id) DO UPDATE SET purpose='reservation',state='pending',attempts=0,
                             available_at=NOW(),last_error=NULL,updated_at=NOW()""",
                        (user_id,),
                    )
                    connection.execute(
                        "UPDATE teams SET provisioning_state='pending',provisioning_error=NULL WHERE id=%s",
                        (user_id,),
                    )
                connection.execute(
                    "INSERT INTO audit_events(team_id,event_type,details) VALUES (%s,'storage_migrated',%s::jsonb)",
                    (user_id, json.dumps({"sources": copied, "workspace": str(workspace)})),
                )
        print(f"user {user_id}: " + (f"copied {', '.join(copied)}" if copied else "no legacy volumes"))

    print("Migration complete. Source volumes were retained as rollback copies.")


if __name__ == "__main__":
    main()
