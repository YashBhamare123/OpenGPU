import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response

import api
from api import current_user, enforce_origin, require_admin, settings


def test_self_booking_is_blocked_without_smtp(monkeypatch):
    monkeypatch.setattr(api, "smtp_enabled", lambda: False)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    request = api.ReservationRequest(start_time=start, end_time=start + timedelta(minutes=30))
    with pytest.raises(HTTPException) as error:
        api.create_reservation(request, user={"id": 1, "is_admin": False}, idempotency_key="test-smtp-off")
    assert error.value.status_code == 403


def test_standard_reservation_limit_is_enforced_before_database_access(monkeypatch):
    monkeypatch.setattr(api, "smtp_enabled", lambda: True)
    monkeypatch.setattr(api, "settings", replace(api.settings, reservation_limit_minutes=120))
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    request = api.ReservationRequest(start_time=start, end_time=start + timedelta(minutes=135))

    with pytest.raises(HTTPException, match="up to 120 minutes"):
        api.create_reservation(request, user={"id": 1}, idempotency_key="test-limit-key")


def test_private_routes_require_authentication_before_external_access():
    with pytest.raises(HTTPException) as error:
        current_user(session=None)
    assert error.value.status_code == 401


def test_admin_access_is_restricted_to_configured_email(monkeypatch):
    monkeypatch.setattr(api, "settings", replace(api.settings, admin_emails=("mc240041040@iiti.ac.in",)))
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


def test_booking_requires_ssh_public_key(monkeypatch):
    monkeypatch.setattr(api, "smtp_enabled", lambda: True)
    monkeypatch.setattr(api, "self_booking_enabled", lambda: True)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    request = api.ReservationRequest(start_time=start, end_time=start + timedelta(minutes=30))
    with pytest.raises(HTTPException) as error:
        api.create_reservation(request, user={"id": 1, "ssh_key": None}, idempotency_key="test-ssh-key")
    assert error.value.status_code == 400


def test_personal_mode_allows_self_booking_without_smtp(monkeypatch):
    monkeypatch.setattr(api, "smtp_enabled", lambda: False)
    monkeypatch.setattr(api, "settings", replace(api.settings, mode="personal", reservation_limit_minutes=120))
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    request = api.ReservationRequest(start_time=start, end_time=start + timedelta(minutes=30))
    with pytest.raises(HTTPException) as error:
        api.create_reservation(
            request,
            user={"id": 1, "ssh_key": None},
            idempotency_key="test-personal",
        )
    assert error.value.status_code == 400
    assert "SSH public key" in error.value.detail


def test_invalid_ssh_key_is_rejected_before_database_access(monkeypatch):
    monkeypatch.setattr(api, "get_connection", lambda: pytest.fail("must not connect"))
    with pytest.raises(HTTPException) as error:
        api.set_my_ssh_key(api.SshKeyRequest(public_key="not-a-key"), user={"id": 1})
    assert error.value.status_code == 400
