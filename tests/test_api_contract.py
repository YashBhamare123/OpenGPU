import asyncio

import pytest
from fastapi import HTTPException, Response

from api import current_user, enforce_origin, live, settings


def test_liveness_has_no_external_dependency():
    assert live() == {"status": "ok"}


def test_private_routes_require_authentication_before_external_access():
    with pytest.raises(HTTPException) as error:
        current_user(session=None)
    assert error.value.status_code == 401


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
