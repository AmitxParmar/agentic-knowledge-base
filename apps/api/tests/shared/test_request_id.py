"""
tests/shared/test_request_id.py
---------------------------------
Purpose:    Request-ID propagation on the HTTP layer (middleware in
            app/main.py): honor a caller-supplied X-Request-ID, mint one
            otherwise; always echo it back so logs ↔ client ↔ traces join.
Dependencies: pytest, fastapi TestClient.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import create_app


def test_request_id_echoes_caller_supplied() -> None:
    """A Vercel-supplied ID must survive the round trip unchanged."""
    client = TestClient(create_app())
    resp = client.get("/healthz", headers={"X-Request-ID": "web-req-123"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "web-req-123"


def test_request_id_minted_when_absent() -> None:
    """No caller ID → the server mints a UUID and echoes it back."""
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    minted = resp.headers["X-Request-ID"]
    assert uuid.UUID(minted), f"expected a UUID, got {minted!r}"
