/**
 * app/api/devicehub/devices/route.ts
 * ----------------------------------
 * Purpose:    Same-origin proxy for `GET /v1/devices` on the DeviceHub hub.
 *             Keeps the bearer token server-side and avoids CORS.
 * Dependencies: lib/devicehub.ts
 * Scope:      Transport only — no reshaping of the hub's response.
 */

import { proxyJson } from "@/lib/devicehub";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return proxyJson("/v1/devices");
}
