"""
tests/auth/test_jwt_auth.py
---------------------------
Token mint/verify round-trips, failure modes, and the mode-aware
dependency behavior. No DB, no network.
"""

from __future__ import annotations

import uuid

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from app.settings import settings
from src.auth.jwt import AuthError, create_access_token, decode_token
from src.auth.stub import _DEV_USER_ID, _DEV_WORKSPACE_ID, get_user_id, get_workspace_id

USER = uuid.uuid4()
WORKSPACE = uuid.uuid4()


@pytest.fixture(autouse=True)
def _jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", "test-secret-not-used-in-prod")


# ── token mint / verify ───────────────────────────────────────────────────────


def test_roundtrip_returns_original_ids() -> None:
    token = create_access_token(USER, WORKSPACE)
    got_user, got_ws = decode_token(token)
    assert (got_user, got_ws) == (USER, WORKSPACE)


def test_expired_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    token = create_access_token(USER, WORKSPACE, ttl_seconds=-1)
    with pytest.raises(AuthError):
        decode_token(token)


def test_wrong_signature_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", "another-secret")
    token = create_access_token(USER, WORKSPACE)

    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", "test-secret-not-used-in-prod")
    with pytest.raises(AuthError):
        decode_token(token)


def test_missing_secret_fails_closed() -> None:
    token = pyjwt.encode(
        {"sub": str(USER), "ws": str(WORKSPACE)}, "attacker-key", algorithm="HS256"
    )
    with pytest.raises(AuthError):
        decode_token(str(token))


# ── dependencies in jwt mode ──────────────────────────────────────────────────


async def test_deps_resolve_from_bearer_token() -> None:
    token = create_access_token(USER, WORKSPACE)

    ws = await get_workspace_id(x_workspace_id=None, authorization=f"Bearer {token}")
    user = await get_user_id(authorization=f"Bearer {token}")

    assert ws == WORKSPACE
    assert user == USER


async def test_header_override_ignored_in_jwt_mode() -> None:
    """A caller cannot scope to another workspace via headers once jwt is on."""
    token = create_access_token(USER, WORKSPACE)
    forged = str(uuid.uuid4())

    ws = await get_workspace_id(
        x_workspace_id=forged, authorization=f"Bearer {token}"
    )
    assert ws == WORKSPACE


async def test_missing_or_garbled_token_is_generic_401() -> None:
    for bad_auth in (None, "Bearer", "Basic abc", "Bearer not.a.jwt"):
        with pytest.raises(HTTPException) as exc:
            await get_workspace_id(x_workspace_id=None, authorization=bad_auth)
        assert exc.value.status_code == 401
        assert exc.value.detail == "Authentication required."


async def test_workspace_claim_must_be_a_uuid() -> None:
    bogus = pyjwt.encode({"sub": str(USER), "ws": "not-a-uuid"}, settings.AUTH_JWT_SECRET, algorithm="HS256")
    with pytest.raises(HTTPException):
        await get_workspace_id(x_workspace_id=None, authorization=f"Bearer {bogus}")


# ── stub mode unchanged ───────────────────────────────────────────────────────


async def test_stub_mode_keeps_dev_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "stub")

    default_ws = await get_workspace_id(x_workspace_id=None, authorization=None)
    override_ws = await get_workspace_id(
        x_workspace_id=str(WORKSPACE), authorization=None
    )
    user = await get_user_id(authorization=None)

    assert default_ws == _DEV_WORKSPACE_ID
    assert override_ws == WORKSPACE
    assert user == _DEV_USER_ID


async def test_stub_mode_rejects_invalid_header_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "stub")
    with pytest.raises(HTTPException):
        await get_workspace_id(x_workspace_id="garbage", authorization=None)
