# DeviceHub hub

Rust device plane for the Phase 2 telemetry slice. Two logical roles, three
binaries ([ADR-0014](../../docs/DeviceHub/adr/0014-single-process-rust-deploy.md)):

| Binary | Role |
|---|---|
| `api` | Read API, SSE, health checks |
| `worker` | MQTT ingest, heartbeat and retention sweeps |
| `all` | Both in one process (what Render runs) |

Rust owns device truth and safety. The Knowledge Base's Python API and Next.js
app are untouched; the browser never talks to MQTT or the database.

## Run locally

```bash
# 1. Database: a dedicated Neon database, or any disposable Postgres.
cp apps/hub/.env.example apps/hub/.env    # edit credentials

# 2. Broker
DEVICE_PASSWORD=devpass HUB_MQTT_PASSWORD=hubpass \
  ./deploy/mosquitto/gen-passwd.sh
docker compose -f deploy/compose.dev.yaml up -d

# 3. Service
cargo run --bin all
```

Migrations run on boot. The seed creates one tenant and one device
(`nano-01`), so the API has something to return before the hardware exists.

## Endpoints

All `/v1/*` routes require `Authorization: Bearer $HUB_API_TOKEN`.

| Route | Purpose |
|---|---|
| `GET /healthz` | Liveness |
| `GET /readyz` | Database readiness |
| `GET /v1/devices` | Fleet list with latest state |
| `GET /v1/devices/{id}` | One device |
| `GET /v1/devices/{id}/telemetry?limit=&from=&to=` | Bounded history, newest first |
| `GET /v1/stream` | SSE `device.state`; send `Last-Event-ID` to resume |
| `GET /v1/stats` | accepted / duplicates / gaps / dead letters |

## Publish a test frame

```bash
DEVICE=0192f3c4-1a2b-7c3d-8e4f-5a6b7c8d9e0f
docker exec devicehub-dev-mosquitto-1 mosquitto_pub \
  -h localhost -u "d_$DEVICE" -P devpass -q 1 \
  -t "dh/v1/d/$DEVICE/telemetry" \
  -m '{"schema_version":1,"device_id":"'$DEVICE'","boot_id":"0192f3c4-0000-7000-8000-000000000001","seq":1,"ts":"2026-11-17T09:15:02Z","distance_cm":23.4,"line":{"l":120,"c":860,"r":130},"motion":{"state":"idle"}}'
```

## Checks

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test                                  # unit tests
TEST_DATABASE_URL=postgres://... cargo test # adds the migration test
```

The migration test drops and recreates the `core` schema. Point it only at a
disposable database.
