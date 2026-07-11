"""
auth/stub.py
------------
Purpose:    MVP single-tenant auth stub.
            Returns a hardcoded workspace_id so the rest of the system can
            use workspace scoping without real auth being in place (PRD Non-Goal).
Scope:      FastAPI dependency only. Replace get_workspace_id() when RBAC is added.

ponytail: one function, one comment — don't build more than the seam.
"""

import uuid

from fastapi import Header

# ponytail: hardcoded dev workspace — replace with JWT decode when RBAC ships
_DEV_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


async def get_workspace_id(x_workspace_id: str | None = Header(default=None)) -> uuid.UUID:
    """
    FastAPI dependency. Returns workspace_id from header if present, else dev default.
    When RBAC is added: validate JWT here, extract workspace from claims.
    """
    if x_workspace_id:
        return uuid.UUID(x_workspace_id)
    return _DEV_WORKSPACE_ID


async def get_user_id() -> uuid.UUID:
    """Stub user resolver — always returns the dev user for MVP."""
    return _DEV_USER_ID