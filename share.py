from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone

import psycopg

from config import settings
from database import get_connection
from security import (
    InvalidHandle,
    InvalidSshPublicKey,
    generate_token,
    hash_secret,
    normalize_handle,
    parse_ssh_public_key,
    session_expiry,
    ssh_key_public_view,
    ssh_public_key_fingerprint,
)


def _audit(cursor, event_type: str, team_id=None, details=None) -> None:
    cursor.execute(
        "INSERT INTO audit_events(team_id,event_type,details) VALUES (%s,%s,%s::jsonb)",
        (team_id, event_type, json.dumps(details or {})),
    )


def find_team(cursor, identity: str):
    handle = identity.strip().casefold()
    cursor.execute(
        """SELECT id,email,handle,name,enabled,ssh_public_key,provisioning_state
           FROM teams WHERE handle=%s OR email=%s FOR UPDATE""",
        (handle, handle),
    )
    return cursor.fetchone()


def public_base() -> str:
    return (
        os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
        or settings.public_base_url
        or f"http://127.0.0.1:{os.environ.get('API_PORT', '9473')}"
    )


def create_claim(handle: str, *, hours: int | None = None) -> dict:
    if settings.mode != "personal":
        raise SystemExit("opengpu share is available in Personal mode only")
    try:
        suggested = normalize_handle(handle)
    except InvalidHandle as exc:
        raise SystemExit(str(exc)) from exc
    token = secrets.token_urlsafe(16)
    expires = datetime.now(timezone.utc) + timedelta(hours=hours or settings.claim_hours)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO share_claims(token_hash,suggested_handle,expires_at)
                   VALUES (%s,%s,%s)""",
                (hash_secret(token), suggested, expires),
            )
            _audit(cursor, "share_claim_created", None, {"handle": suggested})
        conn.commit()
    finally:
        conn.close()
    return {
        "handle": suggested,
        "url": f"{public_base()}/claim/{token}",
        "expires_at": expires,
        "token": token,
    }


def claim_preview(token: str) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT suggested_handle,expires_at,consumed_at
                   FROM share_claims WHERE token_hash=%s""",
                (hash_secret(token),),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    if not row or row[2] is not None or row[1] <= datetime.now(timezone.utc):
        return None
    return {"handle": str(row[0]), "expires_at": row[1]}


def consume_claim(token: str, handle: str, public_key: str) -> tuple[int, str]:
    try:
        chosen = normalize_handle(handle)
        canonical = parse_ssh_public_key(public_key)
    except (InvalidHandle, InvalidSshPublicKey) as exc:
        raise ValueError(str(exc)) from exc
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT id,suggested_handle,expires_at,consumed_at
                   FROM share_claims WHERE token_hash=%s FOR UPDATE""",
                (hash_secret(token),),
            )
            claim = cursor.fetchone()
            if not claim or claim[3] is not None or claim[2] <= datetime.now(timezone.utc):
                raise ValueError("This invite is invalid or has expired")
            existing = find_team(cursor, chosen)
            if existing and existing[4]:
                user_id = existing[0]
                cursor.execute(
                    "UPDATE teams SET ssh_public_key=%s,display_name=COALESCE(display_name,%s) WHERE id=%s",
                    (canonical, chosen, user_id),
                )
            elif existing:
                user_id = existing[0]
                cursor.execute(
                    """UPDATE teams SET enabled=TRUE,handle=%s,ssh_public_key=%s,
                         display_name=COALESCE(%s,display_name),
                         provisioning_state=CASE WHEN container_name IS NULL THEN 'unprovisioned' ELSE 'ready' END,
                         provisioning_error=NULL WHERE id=%s""",
                    (chosen, canonical, chosen, user_id),
                )
            else:
                cursor.execute("SELECT nextval(pg_get_serial_sequence('teams','id'))")
                user_id = cursor.fetchone()[0]
                cursor.execute(
                    """INSERT INTO teams(id,name,handle,display_name,enabled,provisioning_state,ssh_public_key)
                       VALUES (%s,%s,%s,%s,TRUE,'unprovisioned',%s)""",
                    (user_id, chosen, chosen, chosen, canonical),
                )
            session = generate_token()
            cursor.execute(
                "INSERT INTO sessions(team_id,token_hash,expires_at) VALUES (%s,%s,%s)",
                (user_id, hash_secret(session), session_expiry()),
            )
            cursor.execute(
                "UPDATE share_claims SET consumed_at=NOW(),consumed_team_id=%s WHERE id=%s",
                (user_id, claim[0]),
            )
            _audit(
                cursor,
                "share_claim_consumed",
                user_id,
                {"handle": chosen, "fingerprint": ssh_public_key_fingerprint(canonical)},
            )
        conn.commit()
        return user_id, session
    except psycopg.errors.UniqueViolation as exc:
        conn.rollback()
        raise ValueError("That handle is already in use") from exc
    finally:
        conn.close()


def create_reservation_for(identity: str, start: datetime, end: datetime) -> dict:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            team = find_team(cursor, identity)
            if not team or not team[4]:
                raise SystemExit("User not found")
            if not team[5]:
                raise SystemExit("User has not added an SSH public key")
            key = secrets.token_urlsafe(12)
            cursor.execute(
                """INSERT INTO reservations(team_id,start_time,end_time,idempotency_key,workspace_gb,temp_storage_gb)
                   VALUES (%s,%s,%s,%s,2,100) RETURNING id,start_time,end_time""",
                (team[0], start, end, key),
            )
            row = cursor.fetchone()
            cursor.execute(
                """INSERT INTO provisioning_jobs(team_id,purpose) VALUES (%s,'reservation')
                   ON CONFLICT(team_id) DO UPDATE SET state='pending',purpose='reservation',attempts=0,
                     available_at=NOW(),last_error=NULL,updated_at=NOW()""",
                (team[0],),
            )
            cursor.execute(
                "UPDATE teams SET last_booking_at=NOW(),provisioning_state='pending',provisioning_error=NULL WHERE id=%s",
                (team[0],),
            )
            _audit(cursor, "reservation_created", team[0], {"reservation_id": row[0], "created_by": "cli"})
        conn.commit()
        return {"id": row[0], "start_time": row[1], "end_time": row[2], "handle": str(team[2])}
    except psycopg.errors.ExclusionViolation:
        conn.rollback()
        raise SystemExit("The requested time overlaps another reservation") from None
    except psycopg.Error as exc:
        conn.rollback()
        raise SystemExit("Reservation could not be created") from exc
    finally:
        conn.close()


def revoke_user(identity: str) -> dict:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            team = find_team(cursor, identity)
            if not team:
                raise SystemExit("User not found")
            user_id = team[0]
            cursor.execute(
                """UPDATE reservations SET cancelled=TRUE,cancelled_at=NOW(),
                     cancellation_reason='revoked by operator'
                   WHERE team_id=%s AND NOT cancelled AND end_time>NOW()""",
                (user_id,),
            )
            cursor.execute("UPDATE sessions SET revoked_at=NOW() WHERE team_id=%s AND revoked_at IS NULL", (user_id,))
            cursor.execute(
                """UPDATE share_claims SET consumed_at=COALESCE(consumed_at,NOW())
                   WHERE suggested_handle=%s AND consumed_at IS NULL""",
                (team[2],),
            )
            cursor.execute(
                """UPDATE teams SET enabled=FALSE,provisioning_state='disabled',ssh_public_key=NULL
                   WHERE id=%s""",
                (user_id,),
            )
            _audit(cursor, "user_revoked", user_id, {"handle": str(team[2])})
        conn.commit()
        return {"id": user_id, "handle": str(team[2])}
    finally:
        conn.close()


def ssh_view(canonical: str | None) -> dict | None:
    return ssh_key_public_view(canonical)
