"""
tests/retrieval/test_embedding_provenance.py
--------------------------------------------
chunks.embedding_model must name the origin of each vector so a corpus can
never silently mix embedding spaces (dev hash vectors + real Cohere
vectors). The /readyz `embedding_versions` advisory reads this column.
"""

from __future__ import annotations

import pytest

from app.settings import settings
from src.ingestion.models import Chunk
from src.retrieval.embedder import embedding_model_label


def test_chunk_table_carries_embedding_model_column() -> None:
    # Step 1: schema guard — provenance must travel with the vector row.
    assert "embedding_model" in Chunk.__table__.columns


def test_label_reports_hash_fallback_in_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # Dev escape hatch on + no key → vectors are hash-based, labeled as such.
    monkeypatch.setattr(settings, "ALLOW_EMBEDDING_FALLBACK", True)
    monkeypatch.setattr(settings, "COHERE_API_KEY", "")
    assert embedding_model_label() == "local-hash-256"


def test_label_reports_cohere_model_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ALLOW_EMBEDDING_FALLBACK", False)
    monkeypatch.setattr(settings, "COHERE_EMBED_MODEL", "embed-v3.0")
    assert embedding_model_label() == "embed-v3.0"


def test_label_prefers_cohere_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fallback allowed but a key exists → steady state is still Cohere.
    monkeypatch.setattr(settings, "ALLOW_EMBEDDING_FALLBACK", True)
    monkeypatch.setattr(settings, "COHERE_API_KEY", "test-key")
    monkeypatch.setattr(settings, "COHERE_EMBED_MODEL", "embed-v3.0")
    assert embedding_model_label() == "embed-v3.0"
