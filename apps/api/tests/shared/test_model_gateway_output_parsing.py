"""
tests/shared/test_model_gateway_output_parsing.py
-------------------------------------------------
Hardening: malformed/empty provider output must never crash the run.
Covers _parse_completion: zero choices, malformed tool-arg JSON, non-object
tool args, and the happy path.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from src.shared.model_gateway import (
    ProviderError,
    _parse_completion,
)


def _resp(**kwargs: Any) -> Any:
    return SimpleNamespace(**kwargs)


def _msg(content: str | None, tool_calls: list | None = None) -> Any:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def test_empty_choices_raise_provider_error() -> None:
    with pytest.raises(ProviderError, match="empty response"):
        _parse_completion(_resp(choices=[], usage=None))


def test_malformed_tool_args_are_skipped() -> None:
    tc = SimpleNamespace(
        id="1",
        function=SimpleNamespace(name="retrieve_evidence", arguments="{not json"),
    )
    _, calls = _parse_completion(_resp(choices=[_resp(message=_msg(None, [tc]))], usage=None))
    assert calls == []


def test_non_object_tool_args_are_skipped() -> None:
    tc = SimpleNamespace(
        id="1",
        function=SimpleNamespace(name="retrieve_evidence", arguments=json.dumps([1, 2])),
    )
    _, calls = _parse_completion(_resp(choices=[_resp(message=_msg(None, [tc]))], usage=None))
    assert calls == []


def test_valid_tool_args_parsed_to_dict() -> None:
    tc = SimpleNamespace(
        id="1",
        function=SimpleNamespace(name="retrieve_evidence", arguments='{"query": "refunds"}'),
    )
    _, calls = _parse_completion(_resp(choices=[_resp(message=_msg(None, [tc]))], usage=None))
    assert calls is not None and len(calls) == 1
    assert calls[0].function.arguments == {"query": "refunds"}


def test_plain_content_passes_through() -> None:
    usage = SimpleNamespace(total_tokens=7)
    msg, calls = _parse_completion(_resp(choices=[_resp(message=_msg("hello"))], usage=usage))
    assert msg.content == "hello"
    assert calls is None
