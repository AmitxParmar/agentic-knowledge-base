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

import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

import httpx
import litellm
import logfire

from app.settings import settings
from src.observability.setup import traced_observation
from src.shared.circuit_breaker import breaker
from src.shared.retry import (
    RetryableError,
    is_retryable_exception,
    with_retry,
)

logger = logging.getLogger(__name__)

ModelRoute = Literal["default", "small", "synthesis", "verification"]


# ── Typed errors ─────────────────────────────────────────────────────────────
# Callers (routers, agents) classify failures by these types to surface
# accurate, user-facing error codes instead of a single generic AGENT_ERROR.


class ModelGatewayError(Exception):
    """Base class for every model gateway failure."""


class ProviderError(ModelGatewayError):
    """All configured model providers failed (keys, outage, network)."""


class RateLimitError(ModelGatewayError):
    """A provider is rate limiting the request (HTTP 429 or equivalent)."""


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
    prompt_tokens: int | None
    completion_tokens: int | None


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
    - usage carries the provider's token counts for cost metering.
    """

    content: str | None
    tool_calls: list[ToolCall] | None = None
    usage: _ResponseUsage | None = None


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


def _resolve_models(
    model: str | None,
    *,
    route: ModelRoute = "default",
) -> tuple[str, str]:
    """
    Map caller-supplied or Settings-derived model strings to LiteLLM names.

    LiteLLM routes by a "provider/model" prefix:
      - "groq/llama-3.3-70b-versatile"
      - "openrouter/mistralai/mistral-7b-instruct"

    Returns (primary_model, fallback_model). An explicit model takes precedence
    over a route. Otherwise, small routes use MODEL_GATEWAY_SMALL_MODEL and the
    synthesis route uses MODEL_GATEWAY_SYNTHESIS_MODEL (or the primary model
    when no override is configured). Every route retains the existing
    OpenRouter fallback for availability.
    """
    if model is not None:
        return model, f"openrouter/{settings.MODEL_GATEWAY_OPENROUTER_MODEL}"

    if route in ("small", "verification"):
        selected_model = settings.MODEL_GATEWAY_SMALL_MODEL
    elif route == "synthesis":
        selected_model = settings.MODEL_GATEWAY_SYNTHESIS_MODEL or settings.MODEL_GATEWAY_MODEL
    else:
        selected_model = settings.MODEL_GATEWAY_MODEL

    primary = f"{settings.MODEL_GATEWAY_PROVIDER}/{selected_model}"
    fallback = f"openrouter/{settings.MODEL_GATEWAY_OPENROUTER_MODEL}"
    return primary, fallback


async def _call_llm(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    route: ModelRoute = "default",
    temperature: float = 0.2,
    max_tokens: int = 2048,
    prompt_version: str | None = None,
) -> GatewayResponse:
    """
    Core LLM call, delegated to LiteLLM.

    LiteLLM handles routing, retries, and the fallback chain internally
    (primary → OpenRouter), replacing the manual provider loop we previously
    maintained here.

    Returns a GatewayResponse with parsed tool calls; raises a typed
    ModelGatewayError (RateLimitError / ProviderError) when providers fail,
    or RetryableError for transient non-rate-limit failures.
    """
    primary_model, fallback_model = _resolve_models(model, route=route)

    # Step 0: consult the circuit breaker before spending anything (see
    # _select_lead: tripped primary skipped, double-trip fails fast).
    lead_model, lead_fallbacks, lead_provider = _select_lead(primary_model, fallback_model)

    # Build kwargs — only pass `tools` when the caller supplies any. Omitting
    # it entirely (rather than passing []) prevents the model from calling tools.
    # The per-provider timeout rides INSIDE litellm (not in a wait_for around
    # the call): a slow primary must still let the fallback attempt run. A
    # wait_for here would cancel litellm's fallback loop instead.
    kwargs: dict[str, Any] = {
        "model": lead_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "fallbacks": lead_fallbacks,
        "timeout": settings.MODEL_GATEWAY_PROVIDER_TIMEOUT,
    }
    if tools is not None:
        kwargs["tools"] = tools

    with traced_observation(
        "generate-response",
        as_type="generation",
        input=messages,
        metadata={
            "has_tools": tools is not None,
            "route": route,
            "temperature": temperature,
            "prompt_version": prompt_version,
        },
    ) as generation:
        with logfire.span(
            "model_gateway.call",
            model=lead_model,
            route=route,
            has_tools=tools is not None,
        ):

            async def _do_call() -> Any:
                # Step 1: one litellm cycle (primary → fallback on failure).
                # Fast connection failures raise immediately and are retried
                # below; slow-provider timeouts surface from litellm itself
                # so the fallback attempt still runs.
                return await litellm.acompletion(**kwargs)

            async def _call_once() -> tuple[
                _ResponseMessage, list[ToolCall] | None, _CompletionResponse
            ]:
                # Step 2: attempt the cycle, retrying only fast transient
                # failures. Timeouts are NOT retried here — a timeout already
                # consumed the per-provider budget, and the outer
                # MODEL_GATEWAY_TIMEOUT backstop bounds the total so retries
                # + backoff can never outlive callers (the agent wraps every
                # call in a 30s wait_for).
                try:
                    raw = await asyncio.wait_for(
                        with_retry(
                            _do_call,
                            max_attempts=settings.RETRY_MAX_ATTEMPTS,
                            base_delay=settings.RETRY_BASE_DELAY,
                            max_delay=settings.RETRY_MAX_DELAY,
                            retryable_exceptions=(ConnectionError, IOError, OSError),
                        ),
                        timeout=settings.MODEL_GATEWAY_TIMEOUT,
                    )
                except Exception as exc:  # surface any provider failure uniformly
                    breaker.record_failure(lead_provider)
                    raise _gateway_error(exc, lead_model, generation) from exc
                resp = cast(_CompletionResponse, raw)
                try:
                    msg, parsed_calls = _parse_completion(resp)
                except ProviderError as exc:
                    generation.update(level="ERROR", status_message=str(exc))
                    logfire.error("model_gateway.call.empty_response", model=lead_model)
                    raise
                return msg, parsed_calls, resp

            msg, parsed_calls, resp = await _call_once()
            # Step 3: one bounded retry when tools were requested but the
            # response is completely unusable (no content, no valid calls).
            # A garbage tool turn would otherwise burn a whole agent iteration.
            if tools is not None and not parsed_calls and not (msg.content or "").strip():
                logger.warning("model_gateway: unusable tool response — retrying once")
                logfire.warn("model_gateway.call.unusable_retry", model=lead_model)
                msg, parsed_calls, resp = await _call_once()
            # Step 4: the lead provider answered — clear its failure history.
            breaker.record_success(lead_provider)

        # Record what the model actually returned on the Langfuse generation:
        # bare model name (cost table matches without the LiteLLM prefix),
        # token usage (powers cost/dashboards), OpenAI-shaped output.
        usage = getattr(resp, "usage", None)
        generation.update(
            output=_assistant_output(msg),
            model=_bare_model_name(str(getattr(resp, "model", "") or lead_model)),
            usage_details={
                "input": getattr(usage, "prompt_tokens", 0) or 0,
                "output": getattr(usage, "completion_tokens", 0) or 0,
                "total": getattr(usage, "total_tokens", 0) or 0,
            }
            if usage is not None
            else None,
        )

        logfire.info(
            "model_gateway.call.ok",
            model=lead_model,
            route=route,
            tokens_used=resp.usage.total_tokens if resp.usage else None,
            tool_calls=len(parsed_calls) if parsed_calls else 0,
        )

        return GatewayResponse(content=msg.content, tool_calls=parsed_calls, usage=resp.usage)


def _parse_completion(
    resp: _CompletionResponse,
) -> tuple[_ResponseMessage, list[ToolCall] | None]:
    """Validate and parse a raw completion into our lightweight types.

    Raises ProviderError when the provider returned no choices (instead of an
    IndexError). Malformed tool-call payloads are skipped call-by-call: one
    broken argument string never aborts the whole response.
    """
    # Step 1: a response with zero choices is a protocol violation — the
    # provider replied, but there is no message to read. Fail with a typed
    # error instead of letting `resp.choices[0]` blow up with IndexError.
    if not resp.choices:
        logger.error("model_gateway: provider returned zero choices")
        raise ProviderError("Model returned an empty response")
    msg = resp.choices[0].message
    parsed_calls: list[ToolCall] | None = None
    if msg.tool_calls:
        parsed_calls = []
        for tc in msg.tool_calls:
            # Step 2: decode the JSON argument blob. A broken string is
            # skipped call-by-call so one bad payload can't abort the run.
            try:
                arguments = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "model_gateway: skipping tool call with malformed JSON args (%s)",
                    tc.function.name,
                )
                continue
            # Step 3: the decoded value must be a JSON object. An array or
            # scalar parses fine but would crash every .get() downstream.
            if not isinstance(arguments, dict):
                logger.warning(
                    "model_gateway: skipping tool call with non-object args (%s)",
                    tc.function.name,
                )
                continue
            parsed_calls.append(
                ToolCall(
                    id=tc.id,
                    function=ToolFunction(name=tc.function.name, arguments=arguments),
                )
            )
    return msg, parsed_calls


def _bare_model_name(model: str) -> str:
    """Strip LiteLLM's provider prefix ("groq/x", "openrouter/a/b") so the
    model attribute matches entries in Langfuse's cost/pricing table."""
    return model.rsplit("/", 1)[-1]


def _assistant_output(msg: Any) -> dict[str, Any]:
    """Assistant message in OpenAI format so Langfuse renders it readably;
    tool calls keep their original JSON-encoded argument strings."""
    output: dict[str, Any] = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        output["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return output


def _is_rate_limit(exc: Exception) -> bool:
    """Heuristic for rate-limit failures across providers."""
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    text = str(exc).lower()
    return status == 429 or "429" in text or "rate limit" in text or "rate_limit" in text


def _select_lead(primary_model: str, fallback_model: str) -> tuple[str, list[str], str]:
    """Pick the model + fallback chain for this call (breaker-aware).

    Returns (lead_model, lead_fallbacks, lead_provider). A tripped primary
    is skipped outright (lead with the fallback); when both are tripped the
    call fails fast instead of burning latency on a dead provider.
    """
    # Step 1: resolve both providers from the LiteLLM model strings.
    primary_provider = _provider_of(primary_model)
    fallback_provider = _provider_of(fallback_model)
    # Step 2: skip a tripped primary; fail fast when both are tripped.
    if not breaker.allow(primary_provider):
        if not breaker.allow(fallback_provider):
            logger.warning("model_gateway: all providers skipped by circuit breaker")
            logfire.warn("model_gateway.call.breaker_open", model=primary_model)
            raise ProviderError(
                "All model providers are temporarily unavailable. Please try again shortly."
            )
        logger.info(
            "model_gateway: primary %s skipped by circuit breaker, leading with fallback",
            primary_provider,
        )
        return fallback_model, [], fallback_provider
    return primary_model, [fallback_model], primary_provider


def _provider_of(model: str) -> str:
    """Provider prefix of a LiteLLM model string ("groq/x" → "groq")."""
    # Step 1: split on the first slash; a bare name is its own provider.
    return model.split("/", 1)[0] if "/" in model else model


def _is_timeout(exc: Exception) -> bool:
    """Heuristic for provider-side timeouts across SDKs."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    text = str(exc).lower()
    return "timeout" in text or "timed out" in text


def _gateway_error(exc: Exception, primary_model: str, generation: Any) -> Exception:
    """Map a failed litellm cycle to a typed gateway error.

    Runs after litellm exhausted the primary + fallback chain (or the retry
    budget/backstop fired), so every branch here means "no provider answered".
    """
    # Step 1: timeouts — from litellm's per-provider timeout or the gateway
    # backstop — are provider failures with a clear message, not retry signals.
    if _is_timeout(exc):
        logger.error("model_gateway: call timed out (model=%s)", primary_model)
        logfire.error("model_gateway.call.timeout", model=primary_model)
        generation.update(level="ERROR", status_message="provider request timed out")
        return ProviderError("Model request timed out")
    logger.exception("model_gateway: LiteLLM call failed")
    logfire.error("model_gateway.call.failed", model=primary_model, error=str(exc))
    generation.update(level="ERROR", status_message=type(exc).__name__)
    # Step 2: rate limits keep their typed code through fallback exhaustion.
    # LiteLLM re-raises a plain Exception after the last fallback, so the
    # original 429 status attribute is gone — match on the message instead.
    # Without this, every 429 surfaced as generic AGENT_ERROR downstream.
    classified = _classify_provider_error(exc)
    if isinstance(classified, RateLimitError):
        return classified
    # Step 3: other transient failures keep the retryable signal for callers.
    if is_retryable_exception(exc):
        return RetryableError(str(exc))
    return classified


def _classify_provider_error(exc: Exception) -> ModelGatewayError:
    """Map a raw provider exception to a typed, user-safe gateway error."""
    if _is_rate_limit(exc):
        return RateLimitError("Model provider is rate limited. Please wait a moment and try again.")
    return ProviderError("Model providers are unavailable. Check provider status and try again.")


# ── Public interface ──────────────────────────────────────────────────────────


async def complete(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    route: ModelRoute = "default",
    temperature: float = 0.2,
    max_tokens: int = 2048,
    prompt_version: str | None = None,
) -> str:
    """
    Send a chat completion through the Model Gateway.
    Returns just the assistant's reply text.
    """
    resp = await _call_llm(
        messages,
        model=model,
        route=route,
        temperature=temperature,
        max_tokens=max_tokens,
        prompt_version=prompt_version,
    )
    return resp.content or ""


async def complete_with_tools(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    route: ModelRoute = "default",
    temperature: float = 0.2,
    max_tokens: int = 2048,
    prompt_version: str | None = None,
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
        route=route,
        temperature=temperature,
        max_tokens=max_tokens,
        prompt_version=prompt_version,
    )


@dataclass
class StreamUsage:
    """Token counts delivered as the final item of a completed stream."""

    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


async def complete_stream(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    route: ModelRoute = "default",
    temperature: float = 0.2,
    max_tokens: int = 2048,
    prompt_version: str | None = None,
) -> AsyncGenerator[str | StreamUsage, None]:
    """Stream a chat completion as text deltas, then one final StreamUsage.

    Shares the gateway's routing, fallback chain, breaker, and typed errors
    with _call_llm. No mid-stream retry: a failure partway raises (the caller
    keeps whatever text already streamed, standard streaming behavior).
    """
    primary_model, fallback_model = _resolve_models(model, route=route)

    # Step 0: breaker-aware lead selection, same as the blocking path.
    lead_model, lead_fallbacks, lead_provider = _select_lead(primary_model, fallback_model)

    kwargs: dict[str, Any] = {
        "model": lead_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "fallbacks": lead_fallbacks,
        "timeout": settings.MODEL_GATEWAY_PROVIDER_TIMEOUT,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    with (
        traced_observation(
            "generate-response",
            as_type="generation",
            input=messages,
            metadata={
                "has_tools": False,
                "route": route,
                "temperature": temperature,
                "prompt_version": prompt_version,
                "stream": True,
            },
        ) as generation,
        logfire.span(
            "model_gateway.stream",
            model=lead_model,
            route=route,
        ),
    ):
        # Step 1: open the stream (bounded by the gateway SLA); a failure
        # here means no provider answered at all.
        try:
            stream = cast(
                Any,
                await asyncio.wait_for(
                    litellm.acompletion(**kwargs),
                    timeout=settings.MODEL_GATEWAY_TIMEOUT,
                ),
            )
        except Exception as exc:
            breaker.record_failure(lead_provider)
            raise _gateway_error(exc, lead_model, generation) from exc

        # Step 2: forward text deltas; capture usage when the provider
        # attaches it (usually on the final chunk).
        usage = StreamUsage()
        deltas = 0
        try:
            async for chunk in stream:
                for choice in getattr(chunk, "choices", None) or []:
                    text = getattr(getattr(choice, "delta", None), "content", None)
                    if text:
                        deltas += 1
                        yield text
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = StreamUsage(
                        total_tokens=getattr(chunk_usage, "total_tokens", 0) or 0,
                        prompt_tokens=getattr(chunk_usage, "prompt_tokens", 0) or 0,
                        completion_tokens=getattr(chunk_usage, "completion_tokens", 0) or 0,
                    )
        except Exception as exc:
            breaker.record_failure(lead_provider)
            generation.update(level="ERROR", status_message=type(exc).__name__)
            logfire.error("model_gateway.stream.failed", model=lead_model)
            raise _gateway_error(exc, lead_model, generation) from exc

        # Step 3: the lead provider delivered — clear its failure history
        # and close out telemetry with the final usage split.
        breaker.record_success(lead_provider)
        generation.update(
            model=_bare_model_name(lead_model),
            usage_details={
                "input": usage.prompt_tokens,
                "output": usage.completion_tokens,
                "total": usage.total_tokens,
            },
        )
        logfire.info(
            "model_gateway.stream.ok",
            model=lead_model,
            route=route,
            tokens_used=usage.total_tokens or None,
            deltas=deltas,
        )
        yield usage


# ── Speech (TTS) ─────────────────────────────────────────────────────────────
# Hosted TTS for the voice channel (ADR-006 amendment): same rule as chat —
# feature code calls this interface, never a provider endpoint directly.

_GROQ_SPEECH_URL = "https://api.groq.com/openai/v1/audio/speech"


def _speech_client() -> httpx.AsyncClient:
    """One bounded client per speech call; tests swap this for a MockTransport client."""
    return httpx.AsyncClient(timeout=settings.MODEL_GATEWAY_PROVIDER_TIMEOUT)


async def speech(
    text: str,
    *,
    voice: str | None = None,
    model: str | None = None,
) -> bytes:
    """
    Synthesize `text` to WAV bytes with the hosted Groq Orpheus model.

    The provider caps one request at 200 characters — callers chunk long
    answers (see `research/voice_tts.split_for_tts`). Raises typed gateway
    errors: RateLimitError on 429, ProviderError on anything else, so voice
    callers keep their single "fall back to text-only" path.
    """
    # Step 1: build one OpenAI-shaped speech request using the gateway's
    # existing Groq credential — no new key, no provider SDK.
    payload = {
        "model": model or settings.VOICE_TTS_MODEL,
        "input": text,
        "voice": voice or settings.VOICE_TTS_VOICE,
        "response_format": "wav",
    }
    headers = {"Authorization": f"Bearer {settings.MODEL_GATEWAY_GROQ_API_KEY}"}
    # Step 2: bounded single POST; network failures map to ProviderError.
    try:
        async with _speech_client() as client:
            resp = await client.post(_GROQ_SPEECH_URL, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        logger.exception("model_gateway.speech: request failed")
        raise ProviderError("TTS provider is unavailable") from exc
    # Step 3: classify the response — 429 keeps its typed code (mirrors chat),
    # everything else non-2xx is a provider failure; success returns WAV bytes.
    if resp.status_code == 429:
        raise RateLimitError("TTS provider is rate limited. Please wait a moment and try again.")
    if resp.status_code != 200:
        logger.error("model_gateway.speech: %s %s", resp.status_code, resp.text[:200])
        raise ProviderError("TTS provider is unavailable")
    return resp.content
