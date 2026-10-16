"""
shared/circuit_breaker.py
-------------------------
Per-provider circuit breaker for model calls (maturity plan §7).

Opens after N failures inside a sliding window; while open the provider is
skipped without burning rate limits or user latency. After a cooldown a
single probe is allowed through (half-open): success closes the breaker,
failure re-opens it.

Scope: advisory, process-local state. Multi-worker deployments trip one
breaker per worker — each still stops hammering a dead provider, which is
the goal. A Redis-backed breaker (shared across workers) is a future step.
No locks: transitions are single dict operations, and a missed update only
delays (never breaks) the open/close decision.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

import logfire

logger = logging.getLogger(__name__)


@dataclass
class _ProviderState:
    failures: deque[float] = field(default_factory=deque)
    open_until: float = 0.0
    half_open_probe: bool = False


class CircuitBreaker:
    """Sliding-window failure breaker, keyed by provider name."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        window_seconds: float = 30.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self._threshold = failure_threshold
        self._window = window_seconds
        self._cooldown = cooldown_seconds
        self._states: dict[str, _ProviderState] = {}

    def _state(self, provider: str) -> _ProviderState:
        # Step 1: lazily create per-provider state on first use.
        state = self._states.get(provider)
        if state is None:
            state = _ProviderState()
            self._states[provider] = state
        return state

    def allow(self, provider: str) -> bool:
        """Whether a call to this provider may proceed right now."""
        # Step 1: a breaker that never opened always allows.
        state = self._state(provider)
        now = time.monotonic()
        if state.open_until <= 0.0:
            return True
        # Step 2: inside the cooldown window — skip the provider entirely.
        if now < state.open_until:
            return False
        # Step 3: cooldown elapsed — admit exactly one half-open probe;
        # concurrent callers wait for the probe's verdict.
        if not state.half_open_probe:
            state.half_open_probe = True
            logger.info("circuit_breaker: half-open probe for %s", provider)
            logfire.info("circuit_breaker.half_open", provider=provider)
            return True
        return False

    def record_success(self, provider: str) -> None:
        """A call succeeded — clear failures and close an open breaker."""
        # Step 1: drop the failure history; a success resets the window.
        state = self._state(provider)
        was_open = state.open_until > 0.0
        state.failures.clear()
        state.open_until = 0.0
        state.half_open_probe = False
        # Step 2: log the close only when it was actually open.
        if was_open:
            logger.info("circuit_breaker: closed for %s", provider)
            logfire.info("circuit_breaker.closed", provider=provider)

    def record_failure(self, provider: str) -> None:
        """A call failed — open the breaker past the threshold."""
        # Step 1: append now, prune failures outside the sliding window.
        state = self._state(provider)
        now = time.monotonic()
        state.failures.append(now)
        cutoff = now - self._window
        while state.failures and state.failures[0] < cutoff:
            state.failures.popleft()
        # Step 2: a failed half-open probe re-opens immediately.
        if state.half_open_probe:
            state.half_open_probe = False
            self._open(provider, state, now, len(state.failures))
            return
        # Step 3: open once the window holds enough failures.
        if len(state.failures) >= self._threshold and now >= state.open_until:
            self._open(provider, state, now, len(state.failures))

    def snapshot(self) -> dict[str, dict[str, object]]:
        """Read-only view of every provider's breaker state (health endpoint).

        Never mutates: unlike ``allow()`` it does not admit a half-open probe,
        so calling it from ``/readyz`` cannot consume the probe slot.
        """
        # Step 1: one entry per provider that has ever been called.
        now = time.monotonic()
        view: dict[str, dict[str, object]] = {}
        for provider, state in self._states.items():
            if state.open_until <= 0.0:
                status = "closed"
            elif now < state.open_until:
                status = "open"
            else:
                status = "half-open"
            # Step 2: report only failures still inside the sliding window.
            failures = sum(1 for t in state.failures if t >= now - self._window)
            view[provider] = {
                "state": status,
                "failures_in_window": failures,
                "retry_after_seconds": max(0.0, round(state.open_until - now, 1)),
            }
        return view

    def _open(self, provider: str, state: _ProviderState, now: float, failures: int) -> None:
        # Step 1: stamp the cooldown deadline and clear the probe flag.
        state.open_until = now + self._cooldown
        state.half_open_probe = False
        # Step 2: emit the transition for ops visibility.
        logger.warning(
            "circuit_breaker: OPEN for %s (%d failures in window, cooldown %.0fs)",
            provider,
            failures,
            self._cooldown,
        )
        logfire.warn(
            "circuit_breaker.open",
            provider=provider,
            failures_in_window=failures,
            cooldown_seconds=self._cooldown,
        )


# Process-wide breaker used by the model gateway. Constructed from settings
# at import so tests can swap in a short-cooldown instance.
def _default_breaker() -> CircuitBreaker:
    from app.settings import settings

    return CircuitBreaker(
        failure_threshold=settings.CIRCUIT_BREAKER_THRESHOLD,
        window_seconds=settings.CIRCUIT_BREAKER_WINDOW,
        cooldown_seconds=settings.CIRCUIT_BREAKER_COOLDOWN,
    )


breaker = _default_breaker()
