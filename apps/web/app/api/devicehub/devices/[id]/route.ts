/**
 * app/api/devicehub/devices/[id]/route.ts
 * ---------------------------------------
 * Purpose:    Same-origin proxy for `GET /v1/devices/{id}`.
 * Dependencies: lib/devicehub.ts
 * Scope:      Transport only.
 */

import { proxyJson } from "@/lib/devicehub";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return proxyJson(`/v1/devices/${encodeURIComponent(id)}`);
}
