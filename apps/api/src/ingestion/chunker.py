"""
ingestion/chunker.py
--------------------
Purpose:    Semantic chunking via Chonkie + metadata extraction per chunk.
            Boundaries follow meaning shifts, not fixed token counts (F3).
Dependencies: chonkie, ingestion/extractors.py (ExtractedContent)
Scope:      Chunking and metadata inheritance only. No embedding here.

ingestion.md stages 3-4:
  Stage 3 - Semantic chunking (Chonkie)
  Stage 4 - Metadata extraction (author/date/category inherited down to each chunk)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.ingestion.extractors import ExtractedContent

logger = logging.getLogger(__name__)


@dataclass
class ChunkResult:
    """A single semantically-bounded piece of content, ready for embedding."""
    text: str
    position: int          # ordinal within the document
    metadata: dict[str, Any] = field(default_factory=dict)


def chunk_document(
    content: ExtractedContent,
    *,
    source_type: str,
    max_chunk_size: int = 512,   # tokens — Chonkie's target size
    overlap: int = 50,
) -> list[ChunkResult]:
    """
    Split extracted content into semantic chunks.

    For code repos, uses Chonkie's code chunker mode which uses tree-sitter
    internally to respect function/class boundaries (ingestion.md requirement).
    For PDF/audio, uses Chonkie's semantic chunker (embedding-similarity splits).

    Returns chunks with metadata inherited from document-level extraction.
    """
    if source_type == "repo":
        chunks = _chunk_code(content.text, max_chunk_size=max_chunk_size)
    else:
        chunks = _chunk_semantic(content.text, max_chunk_size=max_chunk_size, overlap=overlap)

    # Stage 4: inherit document-level metadata into each chunk
    base_metadata = content.doc_metadata.copy()
    results = [
        ChunkResult(
            text=chunk_text,
            position=i,
            metadata={**base_metadata, "chunk_index": i, "total_chunks": len(chunks)},
        )
        for i, chunk_text in enumerate(chunks)
    ]

    logger.info(
        "chunker: source_type=%s, input_len=%d, chunks=%d",
        source_type,
        len(content.text),
        len(results),
    )
    return results


# ── Chonkie backends ──────────────────────────────────────────────────────────

def _chunk_semantic(text: str, *, max_chunk_size: int, overlap: int) -> list[str]:
    """
    Chonkie SemanticChunker — splits on embedding-similarity drops.
    Boundaries track topic shifts instead of cutting paragraphs in half.
    """
    from chonkie import SemanticChunker  # type: ignore[import-untyped]

    # ponytail: using default BGE-small for chunking similarity (not BGE-M3 for retrieval)
    # They serve different purposes; don't conflate them.
    chunker = SemanticChunker(chunk_size=max_chunk_size, overlap=overlap)
    chunks = chunker.chunk(text)
    return [c.text for c in chunks]


def _chunk_code(text: str, *, max_chunk_size: int) -> list[str]:
    """
    Chonkie CodeChunker — uses tree-sitter under the hood to split on
    function/class boundaries. A cut mid-function is worse than no cut.
    """
    from chonkie import CodeChunker

    chunker = CodeChunker(chunk_size=max_chunk_size)
    chunks = chunker.chunk(text)
    return [c.text for c in chunks]