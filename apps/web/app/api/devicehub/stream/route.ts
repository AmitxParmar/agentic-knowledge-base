/**
 * app/api/devicehub/stream/route.ts
 * ---------------------------------
 * Purpose:    Same-origin SSE passthrough for `GET /v1/stream`.
 *             `EventSource` cannot send an Authorization header, so the
 *             browser subscribes here and this handler attaches the token.
 *             `Last-Event-ID` is forwarded so the hub replays the gap after
 *             a reconnect instead of leaving a hole.
 * Dependencies: lib/devicehub.ts
 * Scope:      Transport only; frames are forwarded byte-for-byte.
 */

import { HubError, errorResponse, hubFetch } from "@/lib/devicehub";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  const lastEventId = request.headers.get("last-event-id");

  try {
    const upstream = await hubFetch("/v1/stream", {
      headers: {
        accept: "text/event-stream",
        ...(lastEventId ? { "last-event-id": lastEventId } : {}),
      },
      signal: request.signal,
      // The stream stays open indefinitely; the hub sends its own keepalive.
      timeoutMs: 0,
    });

    if (!upstream.ok || !upstream.body) {
      return errorResponse(
        new HubError("upstream", `hub stream returned ${upstream.status}`),
      );
    }

    return new Response(upstream.body, {
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
        // Nginx/Render must not buffer the stream.
        "x-accel-buffering": "no",
      },
    });
  } catch (err) {
    return errorResponse(err);
  }
}
