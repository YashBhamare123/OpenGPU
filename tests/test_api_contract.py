import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response

import api
from api import current_user, enforce_origin, require_admin, settings


def test_standard_reservation_limit_is_enforced_before_database_access(monkeypatch):
    monkeypatch.setattr(api, "settings", replace(api.settings, reservation_limit_minutes=120))
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    request = api.ReservationRequest(start_time=start, end_time=start + timedelta(minutes=135))

    with pytest.raises(HTTPException, match="up to 120 minutes"):
        api.create_reservation(request, user={"id": 1}, idempotency_key="test-limit-key")


def test_private_routes_require_authentication_before_external_access():
    with pytest.raises(HTTPException) as error:
        current_user(session=None)
    assert error.value.status_code == 401


def test_admin_access_is_restricted_to_configured_email():
    admin = {"email": "mc240041040@iiti.ac.in"}
    assert require_admin(admin) is admin
    with pytest.raises(HTTPException) as error:
        require_admin({"email": "user@iiti.ac.in"})
    assert error.value.status_code == 403


def test_foreign_origin_is_rejected():
    request = type("Request", (), {
        "method": "POST",
        "headers": {"origin": "https://evil.example"},
    })()

    async def next_handler(_request):
        return Response("unexpected")

    previous = settings.allowed_origins
    try:
        object.__setattr__(settings, "allowed_origins", ("https://internal.example.edu",))
        response = asyncio.run(enforce_origin(request, next_handler))
        assert response.status_code == 403
    finally:
        object.__setattr__(settings, "allowed_origins", previous)
