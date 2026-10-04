"""
tests/shared/test_prompt_safety.py
----------------------------------
Prompt-boundary hardening: user-text sanitization, untrusted-content
delimiters, and system-prompt leak detection.
"""

from __future__ import annotations

from src.shared.prompt_safety import (
    find_system_prompt_leak,
    sanitize_user_text,
    wrap_document,
)


def test_sanitize_strips_control_chars() -> None:
    assert sanitize_user_text("hello\x00 wor\x07ld\n") == "hello world"


def test_sanitize_keeps_newlines_and_tabs() -> None:
    assert sanitize_user_text("line1\n\tline2") == "line1\n\tline2"


def test_sanitize_strips_whitespace() -> None:
    assert sanitize_user_text("  padded  ") == "padded"


def test_sanitize_truncates_to_max_chars() -> None:
    assert len(sanitize_user_text("x" * 100, max_chars=10)) == 10


def test_sanitize_empty_and_none_like() -> None:
    assert sanitize_user_text("") == ""


def test_wrap_document_adds_delimiters() -> None:
    wrapped = wrap_document("some text")
    assert wrapped.startswith("<document>\n")
    assert wrapped.endswith("\n</document>")
    assert "some text" in wrapped


def test_leak_detected_on_verbatim_fragment() -> None:
    prompt = "You are a research assistant that answers questions strictly from the user's uploaded documents."
    answer = f"Sure! {prompt} Now here is your answer."
    assert find_system_prompt_leak(answer, prompt) is True


def test_no_leak_on_normal_answer() -> None:
    prompt = "You are a research assistant that answers questions strictly from the user's uploaded documents."
    answer = "The refund window is 30 days from purchase [1]."
    assert find_system_prompt_leak(answer, prompt) is False


def test_leak_empty_inputs_safe() -> None:
    assert find_system_prompt_leak("", "prompt") is False
    assert find_system_prompt_leak("answer", "") is False
