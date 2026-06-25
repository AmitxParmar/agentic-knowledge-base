"""
model_gateway.py — ADR-003
--------------------------
Single internal interface for all LLM chat/completion calls.
Agents and retrieval code call `complete()` here; they never touch a provider SDK directly.

Fallback chain: Groq (primary) → OpenRouter (secondary).
Adding a third backend = add a new _client_for() branch, zero call-site changes.

ponytail: openai SDK works for both Groq and OpenRouter (same /v1/chat/completions shape),
so we use one SDK with different base_url + api_key — no extra dep.
"""

from __future__ import annotations

import logging
from typing import Any

import logfire
from openai import AsyncOpenAI, APIError

from apps.api.app.settings import settings

logger = logging.getLogger(__name__)


# ── Provider clients (lazy-built, reused) ─────────────────────────────────────

def _groq_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.MODEL_GATEWAY_GROQ_API_KEY,
        base_url=str(settings.MODEL_GATEWAY_GROQ_BASE_URL),
    )


def _openrouter_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.MODEL_GATEWAY_OPENROUTER_API_KEY,
        base_url=str(settings.MODEL_GATEWAY_OPENROUTER_BASE_URL),
        default_headers={
            # OpenRouter wants these for usage tracking
            "HTTP-Referer": "https://research-workspace",
            "X-Title": "Agentic Research Workspace",
        },
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

    Args:
        messages: OpenAI-format message list [{"role": ..., "content": ...}]
        model:    Override the configured model (rarely needed; prefer settings)
        temperature / max_tokens: standard generation params

    Returns:
        The assistant's reply text.

    Raises:
        RuntimeError if both providers fail.
    """
    providers = _provider_chain()

    for provider_name, client, resolved_model in providers:
        try:
            with logfire.span(
                "model_gateway.complete",
                provider=provider_name,
                model=resolved_model,
                message_count=len(messages),
            ):
                resp = await client.chat.completions.create(
                    model=model or resolved_model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                content = resp.choices[0].message.content or ""
                logfire.info(
                    "model_gateway.complete.ok",
                    provider=provider_name,
                    tokens_used=resp.usage.total_tokens if resp.usage else None,
                )
                return content

        except APIError as exc:
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

    raise RuntimeError(
        "Model Gateway: all providers exhausted. Check API keys and provider status."
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _provider_chain() -> list[tuple[str, AsyncOpenAI, str]]:
    """
    Returns ordered list of (name, client, model) to try.
    Primary provider from settings, fallback always OpenRouter.
    ponytail: list literal is fine — two providers, not a registry.
    """
    primary = settings.MODEL_GATEWAY_PROVIDER.lower()

    if primary == "groq":
        return [
            ("groq", _groq_client(), settings.MODEL_GATEWAY_MODEL),
            ("openrouter", _openrouter_client(), settings.MODEL_GATEWAY_OPENROUTER_MODEL),
        ]
    else:
        # openrouter as primary, groq as fallback
        return [
            ("openrouter", _openrouter_client(), settings.MODEL_GATEWAY_OPENROUTER_MODEL),
            ("groq", _groq_client(), settings.MODEL_GATEWAY_MODEL),
        ]
