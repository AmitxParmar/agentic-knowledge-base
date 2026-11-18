/**
 * app/api/devicehub/devices/[id]/telemetry/route.ts
 * -------------------------------------------------
 * Purpose:    Same-origin proxy for `GET /v1/devices/{id}/telemetry`.
 *             Only the documented query parameters are forwarded, so the
 *             dashboard cannot inject arbitrary filters.
 * Dependencies: lib/devicehub.ts
 * Scope:      Transport only.
 */

import { proxyJson } from "@/lib/devicehub";

export const dynamic = "force-dynamic";

const FORWARDED = ["limit", "from", "to"] as const;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  const incoming = new URL(request.url).searchParams;
  const query = new URLSearchParams();

  for (const key of FORWARDED) {
    const value = incoming.get(key);
    if (value !== null) query.set(key, value);
  }

  const serialised = query.toString();
  const suffix = serialised ? `?${serialised}` : "";
  return proxyJson(`/v1/devices/${encodeURIComponent(id)}/telemetry${suffix}`);
}
