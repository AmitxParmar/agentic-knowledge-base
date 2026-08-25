"""
scripts/mint_token.py
---------------------
Mint a workspace-scoped HS256 access token (ADR-008).

Single-tenant bootstrap: there is no login UI yet, so tokens are minted
out-of-band by an operator who already holds AUTH_JWT_SECRET.

Usage (from apps/api/, with AUTH_JWT_SECRET set in .env):
    uv run python scripts/mint_token.py                       # dev defaults
    uv run python scripts/mint_token.py --user <uuid> --workspace <uuid> --ttl 3600

Clients then call the API with:
    Authorization: Bearer <token>
Requires AUTH_MODE=jwt on the server for tokens to be enforced.
"""
from __future__ import annotations

import argparse
import uuid

import src.shared.models  # noqa: F401 — register ORM models
from app.settings import settings
from src.auth.jwt import create_access_token


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mint a workspace-scoped JWT")
    parser.add_argument("--user", type=uuid.UUID, default=uuid.UUID("00000000-0000-0000-0000-000000000002"))
    parser.add_argument("--workspace", type=uuid.UUID, default=uuid.UUID("00000000-0000-0000-0000-000000000001"))
    parser.add_argument("--ttl", type=int, default=None, help="Override token lifetime (seconds)")
    return parser.parse_args()


def main() -> None:
    if not settings.AUTH_JWT_SECRET:
        raise SystemExit("AUTH_JWT_SECRET is not set - refusing to mint a forgeable token.")
    args = _parse_args()
    token = create_access_token(args.user, args.workspace, ttl_seconds=args.ttl)
    print(token)


if __name__ == "__main__":
    main()
