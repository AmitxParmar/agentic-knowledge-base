# `devicehub-bridge`

Reads the Arduino's newline-delimited JSON from a serial port, adds the
contract envelope, and publishes to MQTT. It is the only process that touches
the USB port, and it makes no decisions: Phase 2 is telemetry only.

```
firmware/telemetry ──USB──▶ bridge ──MQTT──▶ hub worker ──▶ Postgres ──▶ API/SSE
```

## What it does

| Concern | Behaviour |
|---|---|
| Parsing | One JSON object per line; trailing `\r` tolerated; wrong `v` rejected |
| Envelope | Adds `device_id`, `boot_id`, `ts`, `fw_version`, `motion.state = idle` |
| Topic | `dh/v1/d/{device_id}/telemetry` |
| Queue | Bounded (`BRIDGE_BUFFER_CAPACITY`); oldest dropped first, drop is logged |
| Delivery | QoS 1; an event leaves the queue only after `PUBACK` |
| Broker outage | Reconnects with exponential backoff (1 s → 30 s); process never exits |
| Serial outage | Reopens the port every second; a reopen starts a new `boot_id` |

`boot_id` is per **serial session**, so unplugging the board or resetting it
starts a new one. It cannot see a reset that happens without the port dropping.

## Run

```bash
# Linux build prerequisite for `serialport`
sudo apt-get install -y libudev-dev pkg-config

cp .env.example .env    # then set MQTT_PASSWORD and HUB_DEVICE_ID
cargo run -p devicehub-bridge
```

The crate is deliberately **not** a default workspace member, so
`cargo build` on a machine without `libudev` still works. CI installs it and
builds with `--workspace`.

## Verify without hardware

The bridge reads any byte stream that looks like a serial port, so a PTY
substitute works:

```bash
python3 -u -c '
import json, time
seq = 0
while True:
    seq += 1
    print(json.dumps({"v":1,"seq":seq,"ms":seq*200,
                      "dist_cm":23.4,"line":{"l":120,"c":860,"r":130}}), flush=True)
    time.sleep(0.2)
' | socat pty,raw,echo=0,link=/tmp/ttyS0 -

BRIDGE_SERIAL_PORT=/tmp/ttyS0 MQTT_PASSWORD=... cargo run -p devicehub-bridge
```

## Checks

```bash
cargo fmt --check
cargo clippy -p devicehub-bridge --all-targets -- -D warnings
cargo test -p devicehub-bridge
```

## Local acceptance evidence (2026-11-17)

| Check | Result |
|---|---|
| Publishes to Mosquitto with the device ACL user | 3 messages with correct topic and envelope |
| Broker stopped for 5 s | bridge stayed alive, logged reconnects |
| Buffered replay | reconnect reported `queued=35`; subscriber then saw `seq` 19, 20, 21… continuing from the last delivered value |
| Original `seq` preserved | yes — no renumbering on replay |
| Duplicate delivery | harmless: the worker dedupes on `(device_id, boot_id, seq)` |
