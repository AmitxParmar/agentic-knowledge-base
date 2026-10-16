"""
shared/prompt_safety.py
-----------------------
Prompt-boundary hardening helpers: user-text sanitization, question length
limits, system-prompt leak detection, and untrusted-content delimiters for
retrieved document chunks.

Scope: pure functions + constants only — no I/O, no settings reads at import
beyond the numeric caps below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_QUESTION_CHARS = 4000
MAX_HISTORY_MESSAGES = 20

# C0/C1 control chars except \t (\x09) and \n (\x0a), plus DEL.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_DOCUMENT_OPEN = "<document>"
_DOCUMENT_CLOSE = "</document>"

# ── Guardrails (ADR-010: deterministic, dependency-free) ─────────────────────
# Classic prompt-injection phrasings. Hits are telemetry-only (see scan_input):
# refusing on a match would also block legitimate questions *about* these
# phrases, while containment comes from delimiters + tool-arg validation.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
        r"disregard\s+(all\s+)?(previous|prior|above|your)\s+(instructions|rules|guidelines)",
        r"(reveal|show|display|print|output)\s+(your|the)\s+(system\s+prompt|instructions|prompt|rules)",
        r"you\s+are\s+now\s+[a-z]",
        r"from\s+now\s+on\s*,?\s*you\s+are",
        r"pretend\s+(you\s+are|to\s+be)",
        r"\bjailbreak\b",
        r"\bDAN\s+mode\b",
        r"developer\s+mode",
        r"(bypass|circumvent|disable)\s+(safety|filter|guardrail|moderation)",
        r"do\s+anything\s+now",
    )
)

# Credential/secret shapes. Hits are REDACTED (never refused): keys must not
# reach provider logs on input nor leak to clients/logs on output. Patterns
# favor precision over recall — a redacted false positive costs a few chars.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"sk-[A-Za-z0-9]{20,}",  # OpenAI-style secret keys
        r"gh[pousr]_[A-Za-z0-9]{20,}",  # GitHub tokens
        r"xox[bap]-[A-Za-z0-9-]{10,}",  # Slack tokens
        r"AKIA[0-9A-Z]{16}",  # AWS access key ids
        r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9\-_]{16,}['\"]?",
        r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?\S{4,}['\"]?",
        r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*",
        r"(?i)aws_secret.{0,10}[:=]\s*['\"]?[A-Za-z0-9/+=]{20,}['\"]?",
    )
)

_REDACTED = "[REDACTED]"


def sanitize_user_text(text: str, *, max_chars: int | None = None) -> str:
    """Strip control characters and surrounding whitespace from user text.

    Keeps newlines and tabs (legitimate in pasted documents/questions).
    When max_chars is given, truncate to that length after cleaning.
    """
    if not text:
        return ""
    # Step 1: remove control characters (keep \n and \t — legit in pasted text).
    # Step 2: trim surrounding whitespace.
    # Step 3: enforce the optional length cap.
    cleaned = _CONTROL_CHARS.sub("", text).strip()
    if max_chars is not None and len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


def wrap_document(text: str) -> str:
    """Wrap retrieved chunk content in explicit untrusted-data delimiters.

    Instructs the model (via the system prompt) to treat the delimited span as
    data, never as instructions — a baseline against indirect prompt injection
    via uploaded documents.
    """
    return f"{_DOCUMENT_OPEN}\n{text}\n{_DOCUMENT_CLOSE}"


def _word_ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    if len(words) < n:
        return set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def find_system_prompt_leak(answer: str, system_prompt: str, *, ngram: int = 5) -> bool:
    """Heuristic: the model echoed a verbatim span of the system prompt.

    Flags the answer when at least two distinct word n-grams of the system
    prompt appear in it — a single overlap is too weak a signal (common
    words), two distinct matches mean distinct verbatim leakage.
    """
    if not answer or not system_prompt:
        return False
    # Step 1: build the set of word n-grams from the secret system prompt.
    prompt_grams = _word_ngrams(system_prompt, ngram)
    if not prompt_grams:
        return False
    # Step 2: count how many of those n-grams appear in the candidate answer.
    # Two distinct matches = distinct verbatim leakage; a single overlap is
    # usually just common words.
    answer_grams = _word_ngrams(answer, ngram)
    return len(prompt_grams & answer_grams) >= 2


@dataclass(frozen=True)
class ScanResult:
    """Outcome of scanning one text boundary (input or output)."""

    flagged: bool
    reasons: list[str] = field(default_factory=list)
    redacted: str = ""


def _match_names(patterns: tuple[re.Pattern[str], ...], text: str) -> list[str]:
    # Step 1: run every pattern, collecting a short name per hit.
    hits: list[str] = []
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            hits.append(match.re.pattern[:48])
    return hits


def redact_secrets(text: str) -> str:
    """Replace credential-shaped substrings with [REDACTED].

    Applied to user input before prompt construction (keys must not reach
    provider logs) and to answers before persist/cache/delivery (chunks can
    carry keys that must not echo to clients).
    """
    # Step 1: fold every secret shape to the same placeholder.
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def scan_input(text: str) -> ScanResult:
    """Scan user-supplied text at the trust boundary (ADR-010).

    Injection phrases are flagged for telemetry only — never refused (a
    refusal would also block legitimate questions about these phrases;
    containment comes from delimiters + tool-arg validation). Secrets are
    redacted so they never reach the model. Returns the redacted text.
    """
    # Step 1: flag classic injection phrasings (telemetry, not refusal).
    reasons = [f"injection:{name}" for name in _match_names(_INJECTION_PATTERNS, text)]
    # Step 2: redact credentials before the text enters any prompt.
    redacted = redact_secrets(text)
    if redacted != text:
        reasons.append("secrets:redacted")
    return ScanResult(flagged=bool(reasons), reasons=reasons, redacted=redacted)


def scan_output(text: str, system_prompt: str) -> ScanResult:
    """Scan model output before persist/cache/delivery (ADR-010).

    Flags system-prompt leakage (the caller replaces the answer on hit) and
    redacts secrets echoed from retrieved chunks. Returns the redacted text.
    """
    # Step 1: leak check against the active system prompt.
    reasons: list[str] = []
    if find_system_prompt_leak(text, system_prompt):
        reasons.append("leak:system-prompt")
    # Step 2: redact credentials before the text leaves the server.
    redacted = redact_secrets(text)
    if redacted != text:
        reasons.append("secrets:redacted")
    return ScanResult(flagged=bool(reasons), reasons=reasons, redacted=redacted)
