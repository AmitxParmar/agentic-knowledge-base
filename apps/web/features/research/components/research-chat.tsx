/**
 * features/research/components/research-chat.tsx
 * ----------------------------------------------
 * Purpose:    Perplexity-style conversation thread. One row per message —
 *             the user's question as a soft card, the assistant answer as a
 *             readable text column with inline [n] citations. While a run
 *             streams, the canonical progress stages render INLINE above the
 *             answer via ThinkingTrace (docs/ux.md vocabulary only); once
 *             settled the trace collapses to an expandable summary and the
 *             sources panel (ContextCards) lands below the answer.
 * Dependencies: api/use-research-chat.ts, api/use-model-info.ts,
 *               thinking-trace.tsx, prompt-bar.tsx, context-cards.tsx,
 *               citation-ref.tsx
 * Scope:      Research page conversation surface.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { useResearchChat } from "../api/use-research-chat";
import { useModelInfo } from "../api/use-model-info";
import { ContextCards } from "./context-cards";
import { MarkdownRenderer } from "./markdown-renderer";
import { PromptBar } from "./prompt-bar";
import { ThinkingTrace } from "./thinking-trace";
import { groupCitations, type Citation } from "../utils/parse-citations";
import type { RunEvent } from "../api/use-research-run";
import type { UIMessage } from "@tanstack/ai-client";

/** A settled run frozen per answer message, so past answers keep their summary. */
interface SettledTrace {
  messageId: string;
  stages: string[];
  sourcesCount: number;
}

function shortModelName(model: string | undefined): string | null {
  if (!model) return null;
  const parts = model.split("/");
  return (parts[parts.length - 1] ?? model).slice(0, 28);
}

export function ResearchChat({
  threadId,
  initialMessages,
  citations,
  stages,
  runStatus,
  runError,
  disabled,
  isCheckingReady = false,
  onQuestion,
  onRunEvent,
  onMessagesChange,
  onToggleUpload,
  showUpload = false,
}: {
  threadId: string;
  initialMessages: UIMessage[];
  citations: Citation[];
  stages: string[];
  runStatus: "idle" | "connecting" | "running" | "complete" | "error";
  runError: string | null;
  disabled: boolean;
  isCheckingReady?: boolean;
  onQuestion: (prompt: string) => void;
  onRunEvent: (event: RunEvent) => void;
  onMessagesChange: (messages: UIMessage[]) => void;
  onToggleUpload?: () => void;
  showUpload?: boolean;
}) {
  const { messages, sendMessage, isLoading, error, stop, clear } = useResearchChat(
    threadId,
    initialMessages,
    onRunEvent,
  );
  const [input, setInput] = useState("");
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  const [settledTrace, setSettledTrace] = useState<SettledTrace | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const modelQuery = useModelInfo();

  const grouped = groupCitations(citations);

  // Keep the scroll pinned to the newest message.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages]);

  // Sync the live message list to the conversation store so switching away
  // and back restores this thread's history.
  useEffect(() => {
    onMessagesChange(messages);
  }, [messages, onMessagesChange]);

  async function handleSubmit() {
    const trimmed = input.trim();
    if (!trimmed || isLoading || disabled) return;
    setInput("");
    setRunStartedAt(Date.now());
    onQuestion(trimmed);
    await sendMessage(trimmed);
  }

  // The thinking trace attaches to the newest assistant message while its
  // answer is streaming. On success it freezes into a per-answer summary so
  // the trace survives the next question (which resets run state).
  const lastMessage = messages[messages.length - 1];
  const streamingAnswerId =
    isLoading && lastMessage?.role === "assistant" ? lastMessage.id : null;

  useEffect(() => {
    if (isLoading) {
      setSettledTrace(null);
      return;
    }
    if (runStatus === "complete" && lastMessage?.role === "assistant" && stages.length > 0) {
      setSettledTrace({ messageId: lastMessage.id, stages: [...stages], sourcesCount: grouped.length });
    }
    // Intentionally keyed on run completion only — grouped/stages are frozen
    // at settle time by design.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, runStatus]);

  const showLiveTrace = stages.length > 0;

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="Research conversation">
      {/* header */}
      <header className="flex items-center gap-3 border-b border-line/40 px-4 md:px-8 py-2.5 shrink-0 bg-surface/30">
        <div className="flex items-center gap-2">
          <h2 className="text-[13px] font-semibold text-ink">Thread</h2>
          <span className="font-mono text-[12px] text-ink-3">· {threadId}</span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          {onToggleUpload && (
            <button
              type="button"
              onClick={onToggleUpload}
              aria-expanded={showUpload}
              className="flex h-7 items-center gap-1.5 rounded-control bg-surface-raised/80 px-2.5 text-[12px] font-medium text-ink transition-colors duration-150 hover:bg-hover shadow-btn"
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={showUpload ? "transition-transform duration-200 rotate-90" : "transition-transform duration-200"}
                aria-hidden="true"
              >
                <path d="M9 6l6 6-6 6" />
              </svg>
              <span>Ingest source</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => clear()}
            disabled={messages.length === 0}
            className="flex h-7 items-center rounded-control px-2.5 text-[12px] text-ink-3 transition-colors duration-150 enabled:hover:bg-hover enabled:hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
          >
            Clear
          </button>
        </div>
      </header>

      {/* thread */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div role="log" aria-live="polite" className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 md:px-8 pt-6 pb-12">
          {messages.length === 0 && (
            <div className="flex flex-col items-center gap-2 pt-20 pb-12 text-center" style={{ animation: "fade-up 400ms var(--ease-out-expo) both" }}>
              <p className="text-[22px] font-semibold tracking-tight text-ink">What do you want to know?</p>
              <p className="max-w-md text-[13.5px] leading-relaxed text-ink-3">
                Ask about your ingested documents. Every claim in the answer links back to its source chunk.
              </p>
            </div>
          )}

          {messages.map((message) => {
            const isUser = message.role === "user";
            const isStreamingTarget = message.id === streamingAnswerId;

            const text = message.parts
              .filter((p): p is Extract<typeof p, { type: "text" }> => p.type === "text")
              .map((p) => (typeof p.content === "string" ? p.content : ""))
              .join("");
            const hasText = text.length > 0;

            if (isUser) {
              return (
                <div key={message.id} className="flex justify-end my-1">
                  <div
                    className="max-w-[85%] rounded-card border border-line/60 bg-surface px-4.5 py-3 shadow-card"
                    style={{ animation: "fade-up 300ms var(--ease-out-expo) both" }}
                  >
                    <p className="whitespace-pre-wrap text-[14.5px] leading-relaxed text-ink [overflow-wrap:anywhere]">
                      {text}
                    </p>
                  </div>
                </div>
              );
            }

            return (
              <div key={message.id} className="flex flex-col my-1">
                {(isStreamingTarget ||
                  (!isLoading && runStatus === "error" && message === lastMessage)) &&
                  showLiveTrace && (
                    <ThinkingTrace
                      stages={stages}
                      status={
                        runStatus === "complete"
                          ? "complete"
                          : runStatus === "error"
                            ? "error"
                            : "running"
                      }
                      startedAt={runStartedAt}
                      sourcesCount={grouped.length}
                      autoExpanded={!hasText}
                    />
                  )}

                {!isLoading && settledTrace?.messageId === message.id && (
                  <ThinkingTrace
                    stages={settledTrace.stages}
                    status="complete"
                    startedAt={runStartedAt ?? undefined}
                    sourcesCount={settledTrace.sourcesCount}
                    autoExpanded={false}
                    label="Researched"
                  />
                )}

                <div
                  className={
                    (isStreamingTarget && showLiveTrace) || settledTrace?.messageId === message.id ? "mt-3" : ""
                  }
                >
                  {hasText && (
                    <div className="relative">
                      <MarkdownRenderer content={text} citations={grouped} />
                      {isStreamingTarget && (
                        <span
                          aria-hidden="true"
                          className="ml-1 inline-block h-[1.05em] w-[7px] translate-y-[2px] rounded-[1px] bg-accent align-baseline"
                          style={{ animation: "blink-caret 900ms steps(1) infinite" }}
                        />
                      )}
                    </div>
                  )}

                  {isStreamingTarget && !hasText && stages.length === 0 && (
                    <div className="flex items-center gap-1 py-2" aria-hidden="true">
                      {[0, 1, 2].map((i) => (
                        <span
                          key={i}
                          className="size-1.5 rounded-full bg-ink-3"
                          style={{ animation: `eq-bounce 900ms ease-in-out ${i * 150}ms infinite` }}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {!isLoading && <ContextCards citations={grouped} />}

          {(error || (runStatus === "error" && !stages.length)) && (
            <p className="rounded-card border border-red/30 bg-red/10 px-3.5 py-2.5 text-[13px] leading-relaxed text-red" role="alert">
              {error?.message ?? runError ?? "The research run failed. Try again."}
            </p>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* composer — skeleton while checking readiness to avoid not-allowed flash */}
      <div className="shrink-0 border-t border-line/40 bg-page/95 backdrop-blur-md">
        <div className="mx-auto w-full max-w-5xl px-4 md:px-8 pb-4 pt-3">
          {isCheckingReady ? (
            <div
              className="relative flex flex-col gap-1.5 rounded-[14px] border border-line bg-surface p-1.5 shadow-card animate-pulse"
              aria-busy="true"
              aria-label="Checking workspace"
            >
              <div className="grid grid-cols-[28px_minmax(0,1fr)_auto_28px_28px] items-center gap-x-1">
                <div className="size-7 rounded-[8px] bg-inset" />
                <div className="h-4 mx-2 rounded bg-inset" />
                <div className="h-7 w-16 rounded-[8px] bg-inset" />
                <div className="size-7 rounded-[8px] bg-inset" />
                <div className="size-7 rounded-[8px] bg-inset/70" />
              </div>
            </div>
          ) : (
            <PromptBar
              value={input}
              onChange={setInput}
              onSubmit={handleSubmit}
              onStop={stop}
              busy={isLoading}
              disabled={disabled}
              modelLabel={shortModelName(modelQuery.data?.model)}
              onAttachClick={onToggleUpload}
            />
          )}
          <p className="px-1 pt-2 text-center text-[11.5px] text-ink-3">
            {isCheckingReady ? "Checking workspace…" : "Answers cite retrieved chunks — verify against the linked sources."}
          </p>
        </div>
      </div>
    </section>
  );
}
