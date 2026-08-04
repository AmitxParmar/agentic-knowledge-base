"""
ingestion/storage.py
--------------------
Purpose:    Durable object storage for raw uploads.
            Cloudflare R2 (S3-compatible) when configured; local filesystem
            fallback for dev. Render's container filesystem is ephemeral, so
            uploads must live in R2 to survive redeploys.
Dependencies: boto3 (optional, R2 only), settings
Scope:      Two operations: store() raw bytes, and open() a source for reading.
            Keeps ingestion/router.py and ingestion/pipeline.py storage-agnostic.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.settings import settings

logger = logging.getLogger(__name__)

# R2 object keys are prefixed so a bucket can hold multiple workspaces/documents.
_PREFIX = "uploads"


def _r2_client() -> Any:
    """Lazy S3 client pointed at Cloudflare R2."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def store(fileobj: Any, *, workspace_id: uuid.UUID, document_id: uuid.UUID, filename: str) -> str:
    """
    Persist an uploaded file, returning a storage reference (R2 key or local path).

    Callers store the returned reference in documents.storage_path and hand it
    back to open() later — they never construct paths themselves.
    """
    if settings.r2_enabled:
        key = f"{_PREFIX}/{workspace_id}/{document_id}_{filename}"
        _r2_client().upload_fileobj(fileobj, settings.R2_BUCKET, key)
        logger.info("storage.store: R2 key=%s", key)
        return key

    # Local fallback (dev) — mirror the historical on-disk layout
    dest = Path(settings.UPLOAD_DIR) / str(workspace_id) / f"{document_id}_{filename}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as buffer:
        shutil.copyfileobj(fileobj, buffer)
    logger.info("storage.store: local path=%s", dest)
    return str(dest)


def open_ref(storage_ref: str) -> Path:
    """
    Return a readable local Path for a storage reference.

    R2 references are downloaded to a temp file (the caller owns cleanup via
    the returned Path); local references are returned as-is.
    """
    if settings.r2_enabled and storage_ref.startswith(f"{_PREFIX}/"):
        tmp = Path(tempfile.mkstemp(suffix=Path(storage_ref).suffix or ".tmp")[1])
        _r2_client().download_file(settings.R2_BUCKET, storage_ref, str(tmp))
        logger.info("storage.open: R2 downloaded to temp=%s", tmp)
        return tmp

    return Path(storage_ref)
