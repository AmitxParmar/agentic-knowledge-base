"""
model_gateway.py — ADR-003
--------------------------
Single internal interface for all LLM chat/completion calls.
Agents and retrieval code call `complete()` or `complete_with_tools()` here;
they never touch a provider SDK directly.

Fallback chain: Groq (primary) → OpenRouter (secondary).
Adding a third backend = add a new _provider_chain() branch, zero call-site changes.

Architecture:
  _call_llm()  — core: provider chain, fallback, logfire spans, tool parsing
  complete()   — thin wrapper, returns str (backward-compatible)
  complete_with_tools() — thin wrapper, returns GatewayResponse with parsed tool calls
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import logfire
from openai import APIError, AsyncOpenAI

from app.settings import settings

logger = logging.getLogger(__name__)


# ── Minimal OpenAI SDK response protocols ─────────────────────────────────────
# ponytail: OpenAI SDK types are partially unknown — stub what we use

class _ChatToolCall(Protocol):
    id: str
    type: str
    function: _ChatFunction


class _ChatFunction(Protocol):
    name: str
    arguments: str  # JSON string, not parsed yet


class _ChatMessage(Protocol):
    content: str | None
    tool_calls: list[_ChatToolCall] | None


class _ChatChoice(Protocol):
    message: _ChatMessage


class _ChatUsage(Protocol):
    total_tokens: int


class _ChatCompletion(Protocol):
    choices: list[_ChatChoice]
    usage: _ChatUsage | None


# ── Response types ────────────────────────────────────────────────────────────
# Lightweight types for tool-calling responses. Keeps the gateway abstracted
# from OpenAI SDK internals — callers never import openai types directly.

@dataclass
class ToolFunction:
    """A parsed function call within a tool invocation."""
    name: str
    arguments: dict[str, Any]  # parsed from JSON, not a raw string


@dataclass
class ToolCall:
    """One tool call requested by the model."""
    id: str
    function: ToolFunction


@dataclass
class GatewayResponse:
    """
    Unified response from all model_gateway calls.
    - complete() populates content only, tool_calls is None
    - complete_with_tools() populates both
    """
    content: str | None
    tool_calls: list[ToolCall] | None = None


# ── Provider clients (lazy-built, reused) ─────────────────────────────────────

def _groq_client() -> AsyncOpenAI:
    """Build Groq client using OpenAI SDK (same /v1/chat/completions shape)."""
    return AsyncOpenAI(
        api_key=settings.MODEL_GATEWAY_GROQ_API_KEY,
        base_url=settings.MODEL_GATEWAY_GROQ_BASE_URL,
    )


def _openrouter_client() -> AsyncOpenAI:
    """Build OpenRouter client — same SDK, different base_url + usage tracking headers."""
    return AsyncOpenAI(
        api_key=settings.MODEL_GATEWAY_OPENROUTER_API_KEY,
        base_url=settings.MODEL_GATEWAY_OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": "https://research-workspace",
            "X-Title": "Agentic Research Workspace",
        },
    )


def _provider_chain() -> list[tuple[str, AsyncOpenAI, str]]:
    """
    Returns ordered list of (name, client, model) to try.
    Primary provider from settings, fallback always OpenRouter.
    """
    primary = settings.MODEL_GATEWAY_PROVIDER.lower()

    if primary == "groq":
        return [
            ("groq", _groq_client(), settings.MODEL_GATEWAY_MODEL),
            ("openrouter", _openrouter_client(), settings.MODEL_GATEWAY_OPENROUTER_MODEL),
        ]
    else:
        # OpenRouter as primary, Groq as fallback
        return [
            ("openrouter", _openrouter_client(), settings.MODEL_GATEWAY_OPENROUTER_MODEL),
            ("groq", _groq_client(), settings.MODEL_GATEWAY_MODEL),
        ]


# ── Core LLM call ─────────────────────────────────────────────────────────────

async def _call_llm(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> GatewayResponse:
    """
    Core LLM call with provider fallback (Groq → OpenRouter).

    Handles:
      - Tool parameter injection (omitted when tools=None to prevent model tool calls)
      - Logfire spans for observability
      - Automatic fallback to next provider on APIError
      - Parsing of OpenAI tool_calls into our lightweight ToolCall dataclasses

    Both complete() and complete_with_tools() delegate here — no duplicate code paths.
    """
    providers = _provider_chain()

    for provider_name, client, resolved_model in providers:
        try:
            # Build request kwargs — only include tools param when caller provides
            # one. Omitting it entirely (not passing tools=[]) prevents the model
            # from attempting any tool calls.
            kwargs: dict[str, Any] = dict(
                model=model or resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if tools is not None:
                kwargs["tools"] = tools

            with logfire.span(
                "model_gateway.call",
                provider=provider_name,
                model=resolved_model,
                message_count=len(messages),
                has_tools=tools is not None,
            ):
                resp: _ChatCompletion = await client.chat.completions.create(**kwargs)  # type: ignore[assignment]

            # Parse the raw SDK response into our lightweight types
            msg = resp.choices[0].message
            parsed_calls: list[ToolCall] | None = None
            if msg.tool_calls:
                parsed_calls = [
                    ToolCall(
                        id=tc.id,
                        function=ToolFunction(
                            name=tc.function.name,
                            # Parse JSON arguments into a dict — callers get a
                            # ready-to-use dict instead of a raw JSON string
                            arguments=json.loads(tc.function.arguments),
                        ),
                    )
                    for tc in msg.tool_calls
                ]

            logfire.info(
                "model_gateway.call.ok",
                provider=provider_name,
                tokens_used=resp.usage.total_tokens if resp.usage else None,
                tool_calls=len(parsed_calls) if parsed_calls else 0,
            )

            return GatewayResponse(content=msg.content, tool_calls=parsed_calls)

        except APIError as exc:
            # Provider failed — log warning and continue to next provider in chain
            logger.warning(
                "model_gateway: provider %s failed (%s), trying next",
                provider_name,
                exc.message,
            )
            logfire.warning(
                "model_gateway.provider_failed",
                provider=provider_name,
                error=str(exc),
            )
            continue

    # All providers exhausted — raise so callers can handle gracefully
    raise RuntimeError(
        "Model Gateway: all providers exhausted. Check API keys and provider status."
    )


# ── Public interface ──────────────────────────────────────────────────────────

async def complete(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    **kwargs: Any,
) -> str:
    """
    Send a chat completion request through the Model Gateway.
    Returns just the assistant's reply text.

    This is the backward-compatible wrapper — existing callers see no change.
    Tool-calling support is available via complete_with_tools() instead.
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
    request tool calls — parsed into GatewayResponse.tool_calls as
    ToolCall dataclasses with dict arguments (not raw JSON strings).
    """
    return await _call_llm(
        messages,
        tools=tools,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
