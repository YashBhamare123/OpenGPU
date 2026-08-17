from __future__ import annotations

from datetime import datetime, timedelta, timezone


def create_claim(handle: str, hours: int | None = None) -> dict:
    hours = 24 if hours is None else hours
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    return {
        "handle": handle,
        "url": f"https://lab.example/claim/{handle}",
        "expires_at": expires,
    }


def create_reservation_for(handle: str, start, end) -> dict:
    return {
        "id": 1,
        "handle": handle,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }


def revoke_user(handle: str) -> dict:
    return {"handle": handle}
