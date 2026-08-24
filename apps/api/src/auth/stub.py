"""
auth/stub.py -> auth dependency resolution (mode-aware, ADR-008)
----------------------------------------------------------------
Purpose:    FastAPI dependencies resolving (user_id, workspace_id).
            AUTH_MODE=stub: dev defaults with X-Workspace-Id override
            (single-tenant MVP behavior - unchanged for local runs).
            AUTH_MODE=jwt: Bearer tokens verified via src/auth/jwt.py;
            failures fail closed with 401.
Scope:      Dependency wiring only. Token minting lives in jwt.py +
            scripts/mint_token.py; no roles/RBAC yet.

The historical module name is kept so every router import
(`from src.auth.stub import get_workspace_id`) stays valid.
"""

from __future__ import annotations

import uuid

from fastapi import Header, HTTPException
from fastapi.security.utils import get_authorization_scheme_param

from app.settings import settings
from src.auth.jwt import AuthError, decode_token

# Dev defaults - the seeded single-tenant workspace/user.
_DEV_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _unauthorized() -> HTTPException:
    # Generic by design: never reveal whether the token was expired,
    # malformed, or signed with the wrong key.
    return HTTPException(status_code=401, detail="Authentication required.")


async def get_workspace_id(
    x_workspace_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> uuid.UUID:
    """Resolve the caller's workspace from the request."""
    if settings.AUTH_MODE == "jwt":
        # Header override is ignored in jwt mode - the token is the source.
        del x_workspace_id
        _, workspace_id = await _authenticate(authorization)
        return workspace_id

    if x_workspace_id:
        try:
            return uuid.UUID(x_workspace_id)
        except ValueError:
            raise _unauthorized() from None
    return _DEV_WORKSPACE_ID


async def get_user_id(authorization: str | None = Header(default=None)) -> uuid.UUID:
    """Resolve the caller's user id from the request."""
    if settings.AUTH_MODE == "jwt":
        user_id, _ = await _authenticate(authorization)
        return user_id
    return _DEV_USER_ID


async def _authenticate(authorization: str | None) -> tuple[uuid.UUID, uuid.UUID]:
    scheme, token = get_authorization_scheme_param(authorization or "")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized()
    try:
        return decode_token(token)
    except AuthError:
        raise _unauthorized() from None
