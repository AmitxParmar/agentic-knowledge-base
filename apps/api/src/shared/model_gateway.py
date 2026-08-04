"""
model_gateway.py — ADR-003
--------------------------
Single internal interface for all LLM chat/completion calls.
Agents and retrieval code call `complete()` or `complete_with_tools()`
here; they never touch a provider SDK directly.

LiteLLM is the concrete implementation behind this interface. It handles
provider routing, retries, and fallback (Groq → OpenRouter), replacing
the hand-rolled provider chain that this module previously maintained.

Architecture:
    complete() / complete_with_tools()  — public interface (unchanged contract)
    _call_llm()                         — LiteLLM delegation + response parsing
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol, cast

import litellm
import logfire

from app.settings import settings

logger = logging.getLogger(__name__)


# ── LiteLLM response shape ──────────────────────────────────────────────────
# litellm.acompletion returns a union of streamed/non-streamed OpenAI-compatible
# responses; its narrow stubs don't expose attributes off a single union member.
# We use this minimal Protocol (same ponytail pattern as the old module) to keep
# the gateway decoupled from any one SDK's typing.

class _ResponseMessage(Protocol):
    content: str | None
    tool_calls: list[Any] | None


class _ResponseChoice(Protocol):
    message: _ResponseMessage


class _ResponseUsage(Protocol):
    total_tokens: int | None


class _CompletionResponse(Protocol):
    choices: list[_ResponseChoice]
    usage: _ResponseUsage | None


# ── Response types ──────────────────────────────────────────────────────────
# Callers never import a provider SDK — these lightweight types are all they see.

@dataclass
class ToolFunction:
    """A parsed function call requested by the model."""
    name: str
    arguments: dict[str, Any]  # parsed from JSON, not a raw string


@dataclass
class ToolCall:
    """One tool invocation requested by the model."""
    id: str
    function: ToolFunction


@dataclass
class GatewayResponse:
    """
    Unified response from every model_gateway call.
    - complete() populates content only; tool_calls is None.
    - complete_with_tools() may populate both.
    """
    content: str | None
    tool_calls: list[ToolCall] | None = None


# ── LiteLLM configuration ──────────────────────────────────────────────────
# LiteLLM reads API keys from environment variables with a provider prefix
# (GROQ_API_KEY, OPENROUTER_API_KEY). We bridge our Settings fields into env
# at import time so settings.py stays the single source of truth and LiteLLM
# wires up as it expects. Idempotent: os.environ only set when not already present.


def _sync_env(key: str, value: str) -> None:
    """Populate `key` in the environment only if empty and we have a value."""
    if value and not os.environ.get(key):
        os.environ[key] = value


_sync_env("GROQ_API_KEY", settings.MODEL_GATEWAY_GROQ_API_KEY)
_sync_env("OPENROUTER_API_KEY", settings.MODEL_GATEWAY_OPENROUTER_API_KEY)


# ── Core LLM call ───────────────────────────────────────────────────────────

def _resolve_models(model: str | None) -> tuple[str, str]:
    """
    Map caller-supplied or Settings-derived model strings to LiteLLM names.

    LiteLLM routes by a "provider/model" prefix:
      - "groq/llama-3.3-70b-versatile"
      - "openrouter/mistralai/mistral-7b-instruct"

    Returns (primary_model, fallback_model). A caller may pass a fully-qualified
    "provider/model" string, in which case that becomes primary and the default
    OpenRouter model is used as fallback.
    """
    if model is not None:
        return model, f"openrouter/{settings.MODEL_GATEWAY_OPENROUTER_MODEL}"

    primary = f"{settings.MODEL_GATEWAY_PROVIDER}/{settings.MODEL_GATEWAY_MODEL}"
    fallback = f"openrouter/{settings.MODEL_GATEWAY_OPENROUTER_MODEL}"
    return primary, fallback


async def _call_llm(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> GatewayResponse:
    """
    Core LLM call, delegated to LiteLLM.

    LiteLLM handles routing, retries, and the fallback chain internally
    (primary → OpenRouter), replacing the manual provider loop we previously
    maintained here.

    Returns a GatewayResponse with parsed tool calls; raises RuntimeError if
    both providers fail, mirroring the old behavior so callers need no changes.
    """
    primary_model, fallback_model = _resolve_models(model)

    # Build kwargs — only pass `tools` when the caller supplies any. Omitting
    # it entirely (rather than passing []) prevents the model from calling tools.
    kwargs: dict[str, Any] = {
        "model": primary_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "fallbacks": [fallback_model],
    }
    if tools is not None:
        kwargs["tools"] = tools

    with logfire.span(
        "model_gateway.call",
        model=primary_model,
        has_tools=tools is not None,
    ):
        try:
            raw = await litellm.acompletion(**kwargs)
        except Exception as exc:  # surface any provider failure uniformly
            logger.exception("model_gateway: LiteLLM call failed")
            logfire.error("model_gateway.call.failed", model=primary_model, error=str(exc))
            # All providers have been exhausted by LiteLLM's controller.
            raise RuntimeError(
                "Model Gateway: all providers exhausted. Check API keys and provider status."
            ) from exc
        resp = cast(_CompletionResponse, raw)

    # Parse the LiteLLM (OpenAI-compatible) response into our lightweight types.
    msg = resp.choices[0].message
    parsed_calls: list[ToolCall] | None = None
    if msg.tool_calls:
        parsed_calls = [
            ToolCall(
                id=tc.id,
                function=ToolFunction(
                    name=tc.function.name,
                    # Parse JSON arguments into a dict — callers get a ready-to-use
                    # dict rather than a raw JSON string.
                    arguments=json.loads(tc.function.arguments),
                ),
            )
            for tc in msg.tool_calls
        ]

    logfire.info(
        "model_gateway.call.ok",
        model=primary_model,
        tokens_used=resp.usage.total_tokens if resp.usage else None,
        tool_calls=len(parsed_calls) if parsed_calls else 0,
    )

    return GatewayResponse(content=msg.content, tool_calls=parsed_calls)


# ── Public interface ──────────────────────────────────────────────────────────

async def complete(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> str:
    """
    Send a chat completion through the Model Gateway.
    Returns just the assistant's reply text.
    """
    resp = await _call_llm(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.content or ""


async def complete_with_tools(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> GatewayResponse:
    """
    Chat completion with optional tool-calling support.

    When tools is None, the model is prevented from calling tools.
    When tools is provided (list of OpenAI tool schemas), the model may
    request tool calls — parsed into GatewayResponse.tool_calls.
    """
    return await _call_llm(
        messages,
        tools=tools,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )