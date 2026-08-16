import hmac
import json
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Annotated

import psycopg
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, field_validator

from config import settings
from database import get_connection
from mailer import deliver_cancellation, deliver_otp, smtp_enabled
from paths import ROOT, frontend_path
from security import (
    generate_otp,
    generate_token,
    hash_secret,
    normalize_email,
    otp_expiry,
    session_expiry,
)

app = FastAPI(title="OpenGPU")
app.mount("/frontend", StaticFiles(directory=frontend_path()), name="frontend")


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


class AdminReservationRequest(ReservationRequest):
    email: EmailStr
    allow_extended: bool = False
    workspace_gb: int = 2
    temp_storage_gb: int = 100


class AdminUserRequest(BaseModel):
    email: EmailStr
    display_name: str | None = None


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
        email = str(row[1])
        return {"id": row[0], "email": email, "username": row[2],
                "display_name": row[3], "provisioning_state": row[5],
                "is_admin": normalize_email(email) in settings.admin_emails,
                "self_booking": smtp_enabled()}
    finally:
        conn.close()


@app.get("/", response_class=HTMLResponse)
def frontend(request: Request):
    base_url = settings.public_base_url or str(request.base_url).rstrip("/")
    html = frontend_path("index.html").read_text(encoding="utf-8")
    html = html.replace("__PUBLIC_URL__", escape(base_url, quote=True))
    return HTMLResponse(html)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(frontend_path("favicon.svg"), media_type="image/svg+xml")


@app.get("/social-card.png", include_in_schema=False)
def social_card():
    return FileResponse(ROOT / "image.png", media_type="image/png")


@app.get("/admin")
def admin_frontend():
    return FileResponse(frontend_path("admin.html"))


def require_admin(user: Annotated[dict, Depends(current_user)]) -> dict:
    if normalize_email(user["email"]) not in settings.admin_emails:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


@app.post("/auth/request-code", status_code=202)
def request_code(request: EmailRequest):
    email = normalize_email(str(request.email))
    conn = get_connection()
    code = None
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM teams WHERE email=%s AND enabled", (email,))
            row = cursor.fetchone()
            if row and (smtp_enabled() or email in settings.admin_emails):
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
            else:
                row = None
        conn.commit()
    finally:
        conn.close()
    if code:
        try:
            deliver_otp(email, code)
        except Exception:  # noqa: BLE001, S110
            # Keep the response generic and avoid exposing SMTP details.
            pass
    return {"detail": "If the address is approved, a login code has been sent.",
            "approved": bool(row),
            "admin_contact": settings.access_contact_email or None}


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
def me(user: Annotated[dict, Depends(current_user)]):
    return {**user, "reservation_limit_minutes": settings.reservation_limit_minutes}


@app.get("/reservations")
def get_reservations(user: Annotated[dict, Depends(current_user)]):
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


@app.get("/admin/users")
def admin_users(_admin: Annotated[dict, Depends(require_admin)]):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT id,email,name,display_name,provisioning_state,enabled
                   FROM teams ORDER BY email"""
            )
            rows = cursor.fetchall()
        return [{"id": row[0], "email": str(row[1]), "username": row[2],
                 "display_name": row[3], "provisioning_state": row[4],
                 "enabled": row[5]} for row in rows]
    finally:
        conn.close()


@app.post("/admin/users", status_code=201)
def admin_whitelist_user(request: AdminUserRequest, admin: Annotated[dict, Depends(require_admin)]):
    email = normalize_email(str(request.email))
    display_name = request.display_name.strip() if request.display_name else None
    if display_name == "":
        display_name = None
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id,enabled FROM teams WHERE email=%s FOR UPDATE", (email,))
            existing = cursor.fetchone()
            if existing and existing[1]:
                raise HTTPException(status_code=409, detail="User is already allowlisted")
            if existing:
                user_id = existing[0]
                cursor.execute(
                    """UPDATE teams SET enabled=TRUE,display_name=COALESCE(%s,display_name),
                         provisioning_state=CASE WHEN container_name IS NULL THEN 'unprovisioned' ELSE 'ready' END,
                         provisioning_error=NULL WHERE id=%s RETURNING name,display_name,provisioning_state""",
                    (display_name, user_id),
                )
                username, saved_name, provisioning_state = cursor.fetchone()
                action = "reenabled"
            else:
                cursor.execute("SELECT nextval(pg_get_serial_sequence('teams','id'))")
                user_id = cursor.fetchone()[0]
                username = f"gpu{user_id}"
                cursor.execute(
                    """INSERT INTO teams(id,name,email,display_name,enabled,provisioning_state)
                       VALUES (%s,%s,%s,%s,TRUE,'unprovisioned')""",
                    (user_id, username, email, display_name),
                )
                saved_name = display_name
                provisioning_state = "unprovisioned"
                action = "created"
            audit(cursor, "admin_user_whitelisted", user_id,
                  {"whitelisted_by_admin": admin["id"], "action": action})
        conn.commit()
        return {"id": user_id, "email": email, "username": username,
                "display_name": saved_name, "enabled": True,
                "provisioning_state": provisioning_state}
    except HTTPException:
        conn.rollback()
        raise
    except psycopg.errors.UniqueViolation as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Email or generated username is already in use") from exc
    finally:
        conn.close()


@app.get("/admin/reservations")
def admin_reservations(_admin: Annotated[dict, Depends(require_admin)]):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT r.id,t.email,t.display_name,t.name,r.start_time,r.end_time,r.duration_override,
                          r.workspace_gb,r.temp_storage_gb
                   FROM reservations r JOIN teams t ON t.id=r.team_id
                   WHERE NOT r.cancelled AND r.end_time>NOW() ORDER BY r.start_time"""
            )
            rows = cursor.fetchall()
        return [{"id": row[0], "email": str(row[1]), "display_name": row[2],
                 "username": row[3], "start_time": row[4], "end_time": row[5],
                 "duration_override": row[6], "workspace_gb": row[7],
                 "temp_storage_gb": row[8]} for row in rows]
    finally:
        conn.close()


@app.post("/admin/reservations")
def admin_create_reservation(request: AdminReservationRequest, admin: Annotated[dict, Depends(require_admin)],
                             idempotency_key: str = Header(min_length=8, max_length=128)):
    email = normalize_email(str(request.email))
    if request.start_time < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reservation cannot start in the past")
    if request.end_time <= request.start_time:
        raise HTTPException(status_code=400, detail="Reservation must end after it starts")
    if (request.end_time > request.start_time + timedelta(minutes=settings.reservation_limit_minutes)
            and not request.allow_extended):
        raise HTTPException(
            status_code=400,
            detail=f"Extended-duration authorization is required for bookings over {settings.reservation_limit_minutes} minutes",
        )
    if request.workspace_gb < 1 or request.temp_storage_gb < 1 or request.workspace_gb + request.temp_storage_gb > 200:
        raise HTTPException(status_code=400, detail="Workspace and temporary storage must each be at least 1 GB and total no more than 200 GB")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id,enabled FROM teams WHERE email=%s FOR UPDATE", (email,)
            )
            target = cursor.fetchone()
            if not target or not target[1]:
                raise HTTPException(status_code=404, detail="Approved user not found")
            target_id = target[0]
            cursor.execute(
                "SELECT id,start_time,end_time,workspace_gb,temp_storage_gb FROM reservations WHERE team_id=%s AND idempotency_key=%s",
                (target_id, idempotency_key),
            )
            existing = cursor.fetchone()
            if existing:
                if (existing[1] != request.start_time or existing[2] != request.end_time
                        or existing[3] != request.workspace_gb or existing[4] != request.temp_storage_gb):
                    raise HTTPException(status_code=409, detail="Idempotency key was used for another request")
                return {"id": existing[0], "start_time": existing[1], "end_time": existing[2]}
            cursor.execute(
                """INSERT INTO reservations(team_id,start_time,end_time,idempotency_key,duration_override,
                                              workspace_gb,temp_storage_gb)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id,start_time,end_time""",
                (target_id, request.start_time, request.end_time, idempotency_key, request.allow_extended,
                 request.workspace_gb, request.temp_storage_gb),
            )
            row = cursor.fetchone()
            cursor.execute(
                """INSERT INTO provisioning_jobs(team_id,purpose) VALUES (%s,'reservation')
                   ON CONFLICT(team_id) DO UPDATE SET state='pending',purpose='reservation',attempts=0,
                     available_at=NOW(),last_error=NULL,updated_at=NOW()""",
                (target_id,),
            )
            cursor.execute(
                "UPDATE teams SET last_booking_at=NOW(),provisioning_state='pending',provisioning_error=NULL WHERE id=%s",
                (target_id,),
            )
            details = {"reservation_id": row[0], "created_by_admin": admin["id"],
                       "duration_override": request.allow_extended,
                       "workspace_gb": request.workspace_gb, "temp_storage_gb": request.temp_storage_gb}
            audit(cursor, "reservation_created", target_id, details)
            audit(cursor, "credential_rotation_requested", target_id, details)
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


@app.delete("/admin/reservations/{reservation_id}", status_code=204)
def admin_cancel_reservation(reservation_id: int, admin: Annotated[dict, Depends(require_admin)]):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE reservations r SET cancelled=TRUE,cancelled_at=NOW(),
                     cancellation_reason='cancelled by administrator'
                   FROM teams t WHERE r.id=%s AND t.id=r.team_id
                     AND NOT r.cancelled AND r.end_time>NOW()
                   RETURNING r.team_id,t.email,r.start_time,r.end_time""",
                (reservation_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Active or future reservation not found")
            audit(cursor, "reservation_cancelled", row[0],
                  {"reservation_id": reservation_id, "cancelled_by_admin": admin["id"]})
        conn.commit()
        try:
            deliver_cancellation(str(row[1]), row[2], row[3])
        except Exception:  # noqa: BLE001, S110
            # Cancellation is authoritative even if the SMTP relay is unavailable.
            pass
    finally:
        conn.close()


@app.post("/reservations")
def create_reservation(request: ReservationRequest, user: Annotated[dict, Depends(current_user)],
                       idempotency_key: str = Header(min_length=8, max_length=128)):
    if not smtp_enabled():
        raise HTTPException(
            status_code=403,
            detail="Self-service booking is disabled without email. An administrator must book this GPU.",
        )
    if request.start_time < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reservation cannot start in the past")
    if request.end_time <= request.start_time:
        raise HTTPException(status_code=400, detail="Reservation must end after it starts")
    if request.end_time > request.start_time + timedelta(minutes=settings.reservation_limit_minutes):
        raise HTTPException(
            status_code=400,
            detail=f"Reservations can be up to {settings.reservation_limit_minutes} minutes",
        )
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
                """INSERT INTO reservations(team_id,start_time,end_time,idempotency_key,workspace_gb,temp_storage_gb)
                   VALUES (%s,%s,%s,%s,2,100) RETURNING id,start_time,end_time""",
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
def cancel_reservation(reservation_id: int, user: Annotated[dict, Depends(current_user)]):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE reservations SET cancelled=TRUE,cancelled_at=NOW(),cancellation_reason='cancelled by user'
                   WHERE id=%s AND team_id=%s AND NOT cancelled AND end_time>NOW()
                   RETURNING id,start_time,end_time""",
                (reservation_id, user["id"]),
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Active or future reservation not found")
            audit(cursor, "reservation_cancelled", user["id"], {"reservation_id": reservation_id})
        conn.commit()
        try:
            deliver_cancellation(user["email"], row[1], row[2])
        except Exception:  # noqa: BLE001, S110
            # Cancellation is authoritative even if the SMTP relay is unavailable.
            pass
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
