"""
auth/jwt.py
-----------
HS256 token minting/verification for workspace-scoped API access (ADR-008).

Tokens are small: subject = user id, plus the workspace claim the deps
use for scoping. No roles/RBAC yet - single-tenant workspaces.

Secret management: AUTH_JWT_SECRET must be set when AUTH_MODE=jwt; a
missing secret fails fast on first use rather than silently minting
forgeable tokens.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt

from app.settings import settings

_ALGORITHM = "HS256"


class AuthError(Exception):
    """Token invalid, expired, or misconfigured auth. Maps to HTTP 401."""


def _secret() -> str:
    secret = settings.AUTH_JWT_SECRET
    if not secret:
        raise AuthError("AUTH_JWT_SECRET is not configured")
    return secret


def create_access_token(
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    ttl_seconds: int | None = None,
) -> str:
    """Mint a signed token carrying user + workspace claims."""
    now = datetime.now(UTC)
    ttl = ttl_seconds if ttl_seconds is not None else settings.AUTH_TOKEN_TTL
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "ws": str(workspace_id),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return pyjwt.encode(claims, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Verify signature/expiry and return (user_id, workspace_id).

    Raises AuthError on any failure - callers map that to a generic 401
    (never leak whether the token was expired vs malformed).
    """
    try:
        claims = pyjwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    except pyjwt.PyJWTError as exc:
        raise AuthError("invalid token") from exc

    try:
        return uuid.UUID(claims["sub"]), uuid.UUID(claims["ws"])
    except (KeyError, ValueError) as exc:
        raise AuthError("token missing required claims") from exc
