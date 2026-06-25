"""
shared/progress.py
------------------
Purpose:    Emit named progress stage events to the client over WebSocket.
            Enforces the fixed vocabulary from docs/ui/ux.md.
            Feature code calls emit(); it never invents new stage strings.
Dependencies: ux.md (vocabulary source), fastapi WebSocket
Scope:      Emission helpers only. Transport wiring is in the API layer.

RULES (ux.md + conventions.md):
- Only strings defined in INGESTION_STAGES / RESEARCH_STAGES are valid.
- Never emit chain-of-thought, raw prompts, or tool-call contents.
- Adding a new stage requires updating ux.md first, then adding it here.
"""

from __future__ import annotations

import json
import logging
from enum import StrEnum

from fastapi import WebSocket

logger = logging.getLogger(__name__)


# ── Fixed vocabulary (ux.md) ──────────────────────────────────────────────────

class IngestionStage(StrEnum):
    UPLOADING   = "Uploading document..."
    EXTRACTING  = "Extracting content..."
    CHUNKING    = "Chunking content..."
    EMBEDDING   = "Creating embeddings..."
    # Stage transitions map: ingestion.md stages 1 → 2 → 3 → 4-5


class ResearchStage(StrEnum):
    SEARCHING   = "Searching documents..."
    REVIEWING   = "Reviewing evidence..."
    GENERATING  = "Generating report..."
    FINALIZING  = "Finalizing answer..."


# ── Emitter ───────────────────────────────────────────────────────────────────

async def emit(ws: WebSocket, stage: IngestionStage | ResearchStage) -> None:
    """
    Send a stage event over an open WebSocket.
    Only IngestionStage / ResearchStage values are accepted — no raw strings.

    The client receives: {"type": "progress", "stage": "<exact string from ux.md>"}
    """
    payload = json.dumps({"type": "progress", "stage": str(stage)})
    try:
        await ws.send_text(payload)
    except Exception as exc:
        # Connection dropped mid-run — log and continue, don't crash the agent
        logger.warning("progress.emit: WebSocket send failed (%s) — continuing run", exc)


async def emit_done(ws: WebSocket) -> None:
    """Signal that the run is complete. Client uses this to stop the spinner."""
    await ws.send_text(json.dumps({"type": "done"}))


async def emit_error(ws: WebSocket, message: str) -> None:
    """
    Signal a terminal error. `message` is user-facing — keep it plain English.
    Never put internal stack traces or model reasoning in message.
    """
    await ws.send_text(json.dumps({"type": "error", "message": message}))
