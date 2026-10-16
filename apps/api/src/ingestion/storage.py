"""
ingestion/storage.py
--------------------
Purpose:    Durable object storage for raw uploads.
            Backblaze B2 (S3-compatible) when configured; local filesystem
            fallback for dev. Render's container filesystem is ephemeral, so
            uploads must live in B2 to survive redeploys.
Dependencies: boto3 (optional, B2 only), settings
Scope:      Two operations: store() raw bytes, and open() a source for reading.
            Keeps ingestion/router.py and ingestion/pipeline.py storage-agnostic.
"""

from __future__ import annotations

import logging
import os
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
    """Lazy S3 client pointed at Backblaze B2."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name=settings.R2_REGION,
    )


def store(
    data: bytes | Any,
    *,
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    filename: str,
) -> str:
    """
    Persist an uploaded file, returning a storage reference (R2 key or local path).

    Accepts either raw bytes or a file-like object. Callers that already have
    the bytes (e.g. after hashing for dedup) pass them directly; the storage
    layer never needs to re-read the stream.
    """
    if settings.r2_enabled:
        key = f"{_PREFIX}/{workspace_id}/{document_id}_{filename}"
        if isinstance(data, bytes):
            from io import BytesIO

            _r2_client().upload_fileobj(BytesIO(data), settings.R2_BUCKET, key)
        else:
            _r2_client().upload_fileobj(data, settings.R2_BUCKET, key)
        logger.info("storage.store: R2 key=%s", key)
        return key

    # Local fallback (dev) — mirror the historical on-disk layout
    dest = Path(settings.UPLOAD_DIR) / str(workspace_id) / f"{document_id}_{filename}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as buffer:
        if isinstance(data, bytes):
            buffer.write(data)
        else:
            shutil.copyfileobj(data, buffer)
    logger.info("storage.store: local path=%s", dest)
    return str(dest)


def delete_ref(storage_ref: str) -> None:
    """Remove a stored object (raw upload) — best-effort, idempotent.

    Local references are unlinked; R2 keys are deleted from the bucket.
    Callers wrap in suppress(): failing to remove the file must never fail
    the row deletion that already happened.
    """
    # Step 1: R2 objects are addressed by their key, not the filesystem.
    if settings.r2_enabled and storage_ref.startswith(f"{_PREFIX}/"):
        _r2_client().delete_object(Bucket=settings.R2_BUCKET, Key=storage_ref)
        logger.info("storage.delete: R2 key=%s", storage_ref)
        return
    # Step 2: local files — missing is fine (idempotent delete).
    path = Path(storage_ref)
    if path.exists():
        path.unlink()
        logger.info("storage.delete: local path=%s", path)


def open_ref(storage_ref: str) -> Path:
    """
    Return a readable local Path for a storage reference.

    R2 references are downloaded to a temp file (the caller owns cleanup via
    the returned Path); local references are returned as-is.
    """
    if settings.r2_enabled and storage_ref.startswith(f"{_PREFIX}/"):
        fd, tmp_path = tempfile.mkstemp(suffix=Path(storage_ref).suffix or ".tmp")
        os.close(fd)
        tmp = Path(tmp_path)
        _r2_client().download_file(settings.R2_BUCKET, storage_ref, str(tmp))
        logger.info("storage.open: R2 downloaded to temp=%s", tmp)
        return tmp

    return Path(storage_ref)
