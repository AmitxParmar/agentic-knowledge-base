# ADR-005: TanStack AI Frontend Runtime (Custom WS Transport)

## Status

Proposed (Phase 3).

## Context

Phase 1+2 built a functional research workspace, but all chat/streaming
state is hand-rolled: `useState` for messages, manual WS lifecycle, manual
loading/error flags, no reconnection. As we add multi-turn features
(follow-up questions, clarification, run retry), this manual state
machinery grows brittle.

[TanStack AI](https://tanstack.com/ai/latest) (`@tanstack/ai`,
`@tanstack/ai-react`, `@tanstack/ai-client`) is a real, actively-maintained
library (npm: `@tanstack/ai` v0.10+, 57K weekly downloads, Tanner Linsley,
MIT license). It provides:

- Framework-agnostic chat state (`messages`, `isLoading`, `error`, `sendMessage`)
- Streaming via pluggable connection adapters
- Client-side tool definitions with `toolDefinition().client()`
- `needsApproval` interrupt/resume for human-in-the-loop flows
- Resumable streams via `@tanstack/ai-persistence`

The decision is **whether and how** to adopt it.

## Constraints

1. The backend research agent (FastAPI + LangGraph) stays the brain. ADR-001
   (LangGraph) and ADR-003 (Model Gateway) are **not** reopened. TanStack AI
   owns the **frontend runtime only**.
2. The backend speaks a **custom WS protocol**
   (`{type:"progress", stage}` / `{type:"answer"}`), not AG-UI.
3. No hosted gateway, no proprietary lock-in (matches project ponytail principle).

## Decision

Adopt TanStack AI via **Option A: a custom WS transport adapter**.

```typescript
import { stream } from "@tanstack/ai-client";

const wsConnection = stream(async (messages, _data, signal) => {
  return createWsEventStream(messages, signal); // wraps existing WS
});
```

The `stream()` adapter accepts a `connectFn` returning an async iterable.
We implement that iterable over our **existing** WebSocket — no backend
change. TanStack AI's `useChat` hook drives the UI state (messages, loading,
error, tool calls) while the transport underneath is our current protocol.

### What TanStack AI gives us (Phase 3)

| Concern | Before (hand-rolled) | After (TanStack AI) |
|---|---|---|
| Message state | `useState` + manual arrays | `useChat().messages` (typed `UIMessage[]`) |
| Loading / error | `useState` per flag | `isLoading`, `error` from hook |
| Streaming | Manual WS `onmessage` | `stream()` adapter yields events |
| Reconnect / cleanup | None | `attach()` / `destroy()` lifecycle |
| Client tools | N/A | `toolDefinition().client()` for copy/clear |

### What TanStack AI does NOT do (keep in backend)

- Agent orchestration (LangGraph)
- Retrieval / embeddings / reranking
- LLM calls (Model Gateway)
- Research agent loop logic

### What is deferred to Phase 4

- `@tanstack/ai-persistence` (resumable streams) — needs a durable
  thread/run pointer the backend doesn't expose yet.
- Tool approval interrupts (`needsApproval`) — no destructive ops in MVP.
- Server-side tool execution — all tools in Phase 3 are client-only.
- Full AG-UI backend (Option B) — possible follow-up if the frontend
  shape proves the adapter pattern works.

## Consequences

### Positive

- Removes all hand-rolled chat state from the research page.
- TanStack AI's `attach()`/`destroy()` lifecycle handles WS cleanup
  automatically (mount/unmount, tab switch).
- Typed message parts (`TextPart`, `ToolCallPart`) give us a clean
  structure for rendering answer text + inline citations.
- Client tools let us add copy/clear/share without new backend routes.

### Negative / mitigations

| Risk | Mitigation |
|---|---|
| New dependencies (3 packages) | All MIT, tree-shakeable, framework-standard. ADR adds them to Approved Libraries. |
| Our protocol is not AG-UI | The `stream()` adapter is transport-agnostic. We bridge WS events → TanStack AI events in the adapter only. |
| TanStack AI is young (v0.10) | API is stable enough for our narrow use case (transport + client tools). We isolate it behind one adapter file, so swapping later is one-file work. |
| Research run is single-shot (one question → one answer), not a multi-turn chat | Each `sendMessage` opens a fresh WS (matching current behavior). TanStack AI's message history gives us a transcript of past runs. |

## Approved Libraries update

Add to `docs/conventions.md` → Approved Libraries table:

| Concern | Library |
|---|---|
| AI frontend runtime / chat state | @tanstack/ai, @tanstack/ai-react, @tanstack/ai-client |
| Tool input/output schemas | zod |

## Packages

```bash
pnpm --filter web add @tanstack/ai @tanstack/ai-react @tanstack/ai-client zod
```

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Keep hand-rolled state | Works now, but grows brittle with multi-turn features. Every new state flag is another `useState` + another effect. |
| Option B: AG-UI proxy endpoint | Cleaner frontend, but requires a new backend route (`/api/research/ag-ui`) that translates our protocol to AG-UI. Backend work we don't need yet. Revisit in Phase 4. |
| Option C: Full AG-UI runtime | Requires rewriting the research WS layer. Conflicts with frozen `ux.md` vocabulary. Too large for Phase 3. |
| Vercel AI SDK (`ai` / `@ai-sdk/react`) | Designed for raw token streaming over standard providers. Our backend streams a fixed WS protocol, not raw tokens. Leaky abstraction. |

## Scope note

This ADR covers **only** the frontend runtime (transport adapter + client
tools + useChat integration). It does not cover agent-framework or routing
libraries. Phase 4 may extend with persistence and AG-UI backend.
