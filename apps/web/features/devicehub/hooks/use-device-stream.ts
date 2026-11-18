/**
 * features/devicehub/hooks/use-device-stream.ts
 * ---------------------------------------------
 * Purpose:    Subscribe to the hub's `device.state` SSE stream through the
 *             same-origin proxy. `EventSource` reconnects on its own and
 *             re-sends `Last-Event-ID`, so the hub replays missed events.
 * Dependencies: features/devicehub/types.ts
 * Scope:      Dashboard live updates.
 */

"use client";

import { useEffect, useState } from "react";
import type { DeviceStateEvent } from "@/features/devicehub/types";

export type StreamStatus =
  | "connecting"
  | "live"
  | "reconnecting"
  | "unsupported";

export interface DeviceStream {
  status: StreamStatus;
  /** Most recent frame; the caller dedupes and retains its own window. */
  event: DeviceStateEvent | null;
  /** Wall-clock time of the last frame, for a "stalled" indicator. */
  lastAt: number | null;
}

export function useDeviceStream(enabled = true): DeviceStream {
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [event, setEvent] = useState<DeviceStateEvent | null>(null);
  const [lastAt, setLastAt] = useState<number | null>(null);

  useEffect(() => {
    if (!enabled) return;
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      setStatus("unsupported");
      return;
    }

    const source = new EventSource("/api/devicehub/stream");

    const onOpen = () => setStatus("live");
    const onState = (message: Event) => {
      const data = (message as MessageEvent<string>).data;
      try {
        setEvent(JSON.parse(data) as DeviceStateEvent);
        setLastAt(Date.now());
        setStatus("live");
      } catch {
        // Malformed frame: ignore rather than break the subscription.
      }
    };
    const onError = () => setStatus("reconnecting");

    source.addEventListener("open", onOpen);
    source.addEventListener("device.state", onState);
    source.addEventListener("error", onError);

    return () => {
      source.removeEventListener("open", onOpen);
      source.removeEventListener("device.state", onState);
      source.removeEventListener("error", onError);
      source.close();
    };
  }, [enabled]);

  return { status, event, lastAt };
}
