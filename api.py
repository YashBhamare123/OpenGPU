import hmac
import json
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, field_validator

from config import settings
from database import get_connection
from mailer import send_otp
from security import (
    generate_otp,
    generate_token,
    hash_secret,
    normalize_email,
    otp_expiry,
    session_expiry,
)


app = FastAPI(title="AIML GPU Reservations")
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


@app.middleware("http")
async def enforce_origin(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and settings.allowed_origins and origin not in settings.allowed_origins:
            return Response("Origin not allowed", status_code=403)
    return await call_next(request)


class EmailRequest(BaseModel):
    email: EmailStr


class VerifyRequest(BaseModel):
    email: EmailStr
    code: str


class ReservationRequest(BaseModel):
    start_time: datetime
    end_time: datetime

    @field_validator("start_time", "end_time")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone offset is required")
        return value.astimezone(timezone.utc)


def audit(cursor, event_type: str, team_id=None, details=None) -> None:
    cursor.execute(
        "INSERT INTO audit_events(team_id,event_type,details) VALUES (%s,%s,%s::jsonb)",
        (team_id, event_type, json.dumps(details or {})),
    )


def current_user(session: str | None = Cookie(default=None)) -> dict:
    if not session:
        raise HTTPException(status_code=401, detail="Authentication required")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.id,t.email,t.name,t.display_name,t.enabled,t.provisioning_state
                FROM sessions s JOIN teams t ON t.id=s.team_id
                WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>NOW()
                """,
                (hash_secret(session),),
            )
            row = cursor.fetchone()
        if not row or not row[4]:
            raise HTTPException(status_code=401, detail="Session is invalid or expired")
        return {"id": row[0], "email": str(row[1]), "username": row[2],
                "display_name": row[3], "provisioning_state": row[5]}
    finally:
        conn.close()


@app.get("/")
def frontend():
    return FileResponse("frontend/index.html")


@app.post("/auth/request-code", status_code=202)
def request_code(request: EmailRequest):
    email = normalize_email(str(request.email))
    conn = get_connection()
    code = None
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM teams WHERE email=%s AND enabled", (email,))
            row = cursor.fetchone()
            if row:
                team_id = row[0]
                cursor.execute(
                    "SELECT COUNT(*) FROM auth_challenges WHERE team_id=%s AND created_at>NOW()-INTERVAL '1 hour'",
                    (team_id,),
                )
                if cursor.fetchone()[0] < 5:
                    code = generate_otp()
                    cursor.execute(
                        "INSERT INTO auth_challenges(team_id,code_hash,expires_at) VALUES (%s,%s,%s)",
                        (team_id, hash_secret(code), otp_expiry()),
                    )
                    audit(cursor, "otp_requested", team_id)
        conn.commit()
    finally:
        conn.close()
    if code:
        try:
            send_otp(email, code)
        except Exception:
            # Keep the response generic and avoid exposing SMTP details.
            pass
    return {"detail": "If the address is approved, a login code has been sent."}


@app.post("/auth/verify-code")
def verify_code(request: VerifyRequest, response: Response):
    email = normalize_email(str(request.email))
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id,c.team_id,c.code_hash,c.attempts
                FROM auth_challenges c JOIN teams t ON t.id=c.team_id
                WHERE t.email=%s AND t.enabled AND c.used_at IS NULL AND c.expires_at>NOW()
                ORDER BY c.created_at DESC LIMIT 1 FOR UPDATE OF c
                """,
                (email,),
            )
            challenge = cursor.fetchone()
            if not challenge or challenge[3] >= settings.otp_max_attempts:
                raise HTTPException(status_code=401, detail="Invalid or expired code")
            cursor.execute("UPDATE auth_challenges SET attempts=attempts+1 WHERE id=%s", (challenge[0],))
            if not hmac.compare_digest(hash_secret(request.code), challenge[2]):
                conn.commit()
                raise HTTPException(status_code=401, detail="Invalid or expired code")
            token = generate_token()
            cursor.execute("UPDATE auth_challenges SET used_at=NOW() WHERE id=%s", (challenge[0],))
            cursor.execute(
                "INSERT INTO sessions(team_id,token_hash,expires_at) VALUES (%s,%s,%s)",
                (challenge[1], hash_secret(token), session_expiry()),
            )
            audit(cursor, "login", challenge[1])
        conn.commit()
    finally:
        conn.close()
    response.set_cookie("session", token, max_age=settings.session_hours * 3600,
                        httponly=True, secure=settings.cookie_secure, samesite="lax")
    return {"authenticated": True}


@app.post("/auth/logout", status_code=204)
def logout(response: Response, session: str | None = Cookie(default=None)):
    if session:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE sessions SET revoked_at=NOW() WHERE token_hash=%s", (hash_secret(session),))
            conn.commit()
        finally:
            conn.close()
    response.delete_cookie("session")


@app.get("/me")
def me(user=Depends(current_user)):
    return user


@app.get("/reservations")
def get_reservations(user=Depends(current_user)):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.id,r.team_id,r.start_time,r.end_time
                FROM reservations r WHERE NOT r.cancelled AND r.end_time>NOW()
                ORDER BY r.start_time
                """
            )
            rows = cursor.fetchall()
        return [{"id": r[0] if r[1] == user["id"] else None,
                 "mine": r[1] == user["id"], "start_time": r[2], "end_time": r[3]}
                for r in rows]
    finally:
        conn.close()


@app.post("/reservations")
def create_reservation(request: ReservationRequest, user=Depends(current_user),
                       idempotency_key: str = Header(min_length=8, max_length=128)):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT enabled,provisioning_state FROM teams WHERE id=%s FOR UPDATE", (user["id"],)
            )
            enabled, _provision_state = cursor.fetchone()
            if not enabled:
                raise HTTPException(status_code=403, detail="User is disabled")
            cursor.execute(
                "SELECT id,start_time,end_time FROM reservations WHERE team_id=%s AND idempotency_key=%s",
                (user["id"], idempotency_key),
            )
            existing = cursor.fetchone()
            if existing:
                if existing[1] != request.start_time or existing[2] != request.end_time:
                    raise HTTPException(status_code=409, detail="Idempotency key was used for another request")
                return {"id": existing[0], "start_time": existing[1], "end_time": existing[2]}
            cursor.execute(
                """INSERT INTO reservations(team_id,start_time,end_time,idempotency_key)
                   VALUES (%s,%s,%s,%s) RETURNING id,start_time,end_time""",
                (user["id"], request.start_time, request.end_time, idempotency_key),
            )
            row = cursor.fetchone()
            cursor.execute(
                """INSERT INTO provisioning_jobs(team_id,purpose) VALUES (%s,'reservation')
                   ON CONFLICT(team_id) DO UPDATE SET state='pending',purpose='reservation',attempts=0,
                     available_at=NOW(),last_error=NULL,updated_at=NOW()""",
                (user["id"],),
            )
            cursor.execute(
                "UPDATE teams SET last_booking_at=NOW(),provisioning_state='pending',provisioning_error=NULL WHERE id=%s",
                (user["id"],),
            )
            audit(cursor, "reservation_created", user["id"], {"reservation_id": row[0]})
            audit(cursor, "credential_rotation_requested", user["id"], {"reservation_id": row[0]})
        conn.commit()
        return {"id": row[0], "start_time": row[1], "end_time": row[2]}
    except HTTPException:
        conn.rollback()
        raise
    except psycopg.errors.ExclusionViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="The requested time overlaps another reservation")
    except psycopg.errors.CheckViolation as exc:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Invalid reservation time or duration") from exc
    except psycopg.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Reservation conflicts with an existing booking") from exc
    finally:
        conn.close()


@app.delete("/reservations/{reservation_id}", status_code=204)
def cancel_reservation(reservation_id: int, user=Depends(current_user)):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE reservations SET cancelled=TRUE,cancelled_at=NOW(),cancellation_reason='cancelled by user'
                   WHERE id=%s AND team_id=%s AND NOT cancelled AND end_time>NOW() RETURNING id""",
                (reservation_id, user["id"]),
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Active or future reservation not found")
            audit(cursor, "reservation_cancelled", user["id"], {"reservation_id": reservation_id})
        conn.commit()
    finally:
        conn.close()


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT last_seen_at,details FROM service_heartbeats WHERE service_name='scheduler'")
            row = cursor.fetchone()
        scheduler_ok = bool(row and row[0] > datetime.now(timezone.utc) - timedelta(seconds=30))
        if not scheduler_ok:
            raise HTTPException(status_code=503, detail="Scheduler heartbeat is stale")
        if row[1].get("error"):
            raise HTTPException(status_code=503, detail="Scheduler reconciliation is degraded")
        return {"status": "ready", "database": "ok", "scheduler": "ok"}
    finally:
        conn.close()
