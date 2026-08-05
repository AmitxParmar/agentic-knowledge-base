"""
ingestion/extractors.py
-----------------------
Purpose:    Source-type-specific content extraction.
            One function per type; all return the same shape so chunker.py
            doesn't care which extractor ran.
Dependencies: docling, faster-whisper, tree-sitter, gitingest (see pyproject.toml)
Scope:      Extraction only — no chunking, no embedding.

Per ingestion.md:
- PDF:   Docling preserves heading hierarchy and tables as structured objects.
- Audio: faster-whisper transcribes to text (treated like any extracted text after).
- Repo:  tree-sitter parses AST; gitingest downloads the repo. Chunks land on function/class boundaries — mid-function cuts are worse than no cut.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExtractedContent:
    """Common output shape from all extractors."""
    # Structured text ready for chunking
    text: str
    # Document-level metadata (author, title, language, etc.)
    doc_metadata: dict[str, Any] = field(default_factory=dict)
    # Per-section/page metadata for chunk inheritance
    section_metadata: list[dict[str, Any]] = field(default_factory=list)


# ── PDF ───────────────────────────────────────────────────────────────────────

def extract_pdf(path: Path) -> ExtractedContent:
    """
    Lightweight PDF text extraction via pypdf.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"

    metadata = {
        "title": reader.metadata.title if reader.metadata else path.stem,
        "page_count": len(reader.pages),
    }

    logger.info("extract_pdf: %s, pages=%s", path.name, metadata["page_count"])
    return ExtractedContent(text=text, doc_metadata=metadata)


# ── Audio ─────────────────────────────────────────────────────────────────────

def extract_audio(path: Path, *, language: str | None = None) -> ExtractedContent:
    """
    faster-whisper transcription (large-v3 via CTranslate2).
    Transcript is plain text; treated identically to extracted PDF text after this.
    ponytail: beam_size=5 is the whisper default — tune if speed matters more than accuracy.
    """
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    # ponytail: model loaded per-call in pipeline worker — consider caching at worker startup
    model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(path), language=language, beam_size=5)

    text = " ".join(seg.text.strip() for seg in segments)
    metadata = {
        "language": info.language,
        "duration_seconds": info.duration,
    }

    logger.info("extract_audio: %s, lang=%s, duration=%.1fs", path.name, info.language, info.duration)
    return ExtractedContent(text=text, doc_metadata=metadata)


# ── Code repo ─────────────────────────────────────────────────────────────────

def extract_repo(path: Path | str) -> ExtractedContent:
    """
    gitingest downloads the repo (if URL) or reads local zip.
    tree-sitter parses each file into AST so chunk boundaries land on
    function/class boundaries — a chunk cut mid-function is worse than no chunk.

    ponytail: gitingest handles the download + file enumeration;
    tree-sitter handles AST parsing. We combine them here.
    """
    from gitingest import ingest  # type: ignore[import-untyped]

    # gitingest returns a structured digest of the repo
    summary, tree, content = ingest(str(path))

    # content is a concatenated view of all files with path headers
    # tree-sitter AST parsing for boundary-aware splitting is done in chunker.py
    # (Chonkie's code chunker mode uses tree-sitter under the hood)
    metadata = {
        "repo_path": str(path),
        "file_tree": tree[:2000],  # truncate for metadata — full content is in text
        "summary": summary[:500],
    }

    logger.info("extract_repo: %s, content_len=%d", path, len(content))
    return ExtractedContent(text=content, doc_metadata=metadata)


# ── Dispatcher ────────────────────────────────────────────────────────────────

def extract(path: Path, source_type: str) -> ExtractedContent:
    """
    Route to the correct extractor based on source_type.
    Called by the ingestion pipeline; never call individual extractors directly.
    """
    match source_type:
        case "pdf":
            return extract_pdf(path)
        case "audio":
            return extract_audio(path)
        case "repo":
            return extract_repo(path)
        case _:
            raise ValueError(f"Unknown source_type: {source_type!r}")