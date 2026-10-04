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

MAX_QUESTION_CHARS = 4000
MAX_HISTORY_MESSAGES = 20

# C0/C1 control chars except \t (\x09) and \n (\x0a), plus DEL.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_DOCUMENT_OPEN = "<document>"
_DOCUMENT_CLOSE = "</document>"


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
