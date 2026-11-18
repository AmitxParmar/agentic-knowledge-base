# DEPLOY — DeviceHub hub on Render (T10)

Only the **hub** is deployed. Everything stateful stays external:

| Piece | Where | Why |
|---|---|---|
| `apps/hub` (API + MQTT ingest + SSE) | **Render**, one free web service, Docker | Needs a public HTTPS URL for the dashboard |
| PostgreSQL | **Neon** | Free Render Postgres would be a second database and a second billing surface |
| MQTT broker | **external broker, TLS** | A free Render web service cannot host a broker |
| Dashboard (`apps/web`) | **Vercel** (or anywhere Next.js runs) | Static/edge-friendly; no cold start for assets |
| Bridge + board | **your machine** | USB serial only exists there |

Image: root [`Dockerfile`](../../Dockerfile), built with `--bin all` (ADR-0014).
Migrations run on boot via `sqlx::migrate!`; there is no release phase.

---

## 1. One-time prerequisites

- The branch must exist on GitHub — Render builds from Git, not from your laptop.
- The Render CLI must be authenticated: `render login` (opens the dashboard).
- A Neon connection string (**pooled**, includes `sslmode=require`).
- Broker credentials for two identities if the provider allows it: `hub` and
  `d_<device_id>`. One shared identity works for a demo but weakens the
  separation described in `SECURITY.md`.

## 2. Create the service (CLI)

```bash
render login                       # once, browser-based

render services create \
  --name devicehub-hub \
  --type web_service \
  --runtime docker \
  --repo https://github.com/AmitxParmar/agentic-knowledge-base \
  --branch feat/devicehub-phase-2-telemetry \
  --plan free \
  --region oregon \
  --health-check-path /healthz \
  --auto-deploy \
  --output json
```

`--region` should be the one closest to your Neon project; cross-region calls
add latency to every request and to each ingest batch.

The first deploy will fail the health check, because no environment variables
exist yet. That is expected — set them next, then redeploy.

### Set environment variables

Dashboard: **Service → Environment → Add Environment Variable**. The CLI has no
secret-aware flag (`--env-var KEY=VALUE` stores plaintext and shows up in shell
history), so use the dashboard for the credentials.

| Variable | Required | Example | Notes |
|---|---|---|---|
| `HUB_DATABASE_URL` | **yes** | `postgresql://…@ep-…-pooler.…neon.tech/devicehub?sslmode=require` | Use the **pooled** Neon URL |
| `HUB_API_TOKEN` | **yes** | 32+ random chars | Must match the web app's `HUB_API_TOKEN` |
| `MQTT_HOST` | **yes** | `xxxx.ala.asia-southeast1.emqxsl.com` | Broker hostname, no scheme |
| `MQTT_PORT` | **yes** | `8883` | TLS port |
| `MQTT_TLS` | **yes** | `true` | Free cloud brokers reject plaintext |
| `MQTT_USERNAME` | **yes** | `hub` | Service identity |
| `MQTT_PASSWORD` | **yes** | `…` | |
| `MQTT_TOPIC_PREFIX` | **yes** | `dh/v1` | Must match the bridge and the broker ACL |
| `CORS_ORIGINS` | no | `https://your-app.vercel.app` | Only needed if a browser calls the hub directly; the dashboard proxies server-side |
| `PORT` | no | set by Render | `Settings` defaults to 8080 |
| `HUB_BIND_HOST` | no | `0.0.0.0` (default) | |
| `DB_MAX_CONNECTIONS` | no | `5` | Neon free handles this comfortably |
| `HEARTBEAT_TIMEOUT_SECS` | no | `15` | Presence timeout |
| `TELEMETRY_RETENTION_HOURS` | no | `48` | Keeps Neon's 0.5 GB budget safe |
| `RUST_LOG` | no | `info` | |

## 3. Deploy and verify

```bash
render deploys create <srv-id> --confirm    # streams build logs
render logs <srv-id> --confirm              # runtime logs

curl -s https://<service>.onrender.com/healthz           # {"status":"ok"}
curl -s https://<service>.onrender.com/readyz            # {"status":"ready"} — proves Neon
curl -s -H "Authorization: Bearer $HUB_API_TOKEN" \
     https://<service>.onrender.com/v1/devices
```

`readyz` returning `503 {"database":"unreachable"}` means the Neon URL is wrong
or unpooled, not that Render failed.

Boot log lines to look for: `hub api listening`, `subscribed`, then
`device marked offline` after 15 s of silence — that last one is normal.

## 4. Point the dashboard at it

On Vercel (or wherever `apps/web` runs):

| Variable | Value |
|---|---|
| `HUB_API_URL` | `https://<service>.onrender.com` |
| `HUB_API_TOKEN` | same token as the hub |

Both are server-only. Do **not** prefix them with `NEXT_PUBLIC_`: the token is
used inside `app/api/devicehub/*` and must never reach the browser bundle.

## 5. Free-tier behaviour that changes the demo

| Behaviour | Consequence | Mitigation |
|---|---|---|
| Sleeps after ~15 min without inbound HTTP | MQTT ingest stops; frames published while asleep are **dropped** (the hub subscribes with `clean_session(true)`, so the broker does not queue them) | Open the dashboard first — its polling wakes the hub — then power the board |
| 30–60 s cold start | First dashboard request shows "Waking the device hub" | The UI already handles this with a retry, not a silent retry loop |
| 750 instance hours/month per **account**, shared with the KB service | Two always-awake services would exceed it | Sleep is what keeps you inside the quota; do not add a keep-warm cron |
| 512 MB / 0.1 CPU | Ingest + API on a current-thread runtime | Fine at 5 Hz for one device |
| No persistent disk | Nothing stateful in the container | Neon owns the data |

A hosted instance is therefore "seeded history + live while awake". That is
exactly the demo model recorded in `PHASE_2_PLAN.md` (O1).

## 6. Troubleshooting

| Symptom | Check |
|---|---|
| Build fails at `cargo build` with signal 9 | Build container ran out of memory. The Dockerfile already disables LTO and raises codegen units; if it still fails, build the image locally and push to a registry instead |
| `/readyz` 503 | Neon URL: pooled host, `sslmode=require`, database exists |
| Dashboard says "Hub rejected the token" | `HUB_API_TOKEN` differs between Render and the web app |
| Device online on the bench but absent in the dashboard | Check `MQTT_TLS`, port 8883, and the broker ACL; `render logs` shows connection errors and `dead_letters` |
| `device marked offline` repeats while the board runs | Broker connection dropped, or the bridge is publishing to another prefix |
| Hub sleeps mid-demo | Expected on free tier. Keep the dashboard open, or run the hub locally for demos |

## 7. Why no `render.yaml` blueprint here

The existing Knowledge Base blueprint (`apps/api/render.yaml`) is applied
separately, and the CLI cannot set `dockerfilePath`/`dockerContext`. Adding a
second blueprint that defines a service created by hand would produce two
sources of truth for the same service. Root `Dockerfile` + the CLI command above
is the single path; the deployment is reproducible from this document.
