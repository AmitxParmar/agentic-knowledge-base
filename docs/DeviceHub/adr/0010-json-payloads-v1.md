# ADR-0010: JSON payloads with explicit schema versions in v1
Status: Accepted (revisit after benchmark) · Date: 2026-11-13

## Context
Debuggability and iteration speed matter early; payload size and parsing cost matter at scale. The MCU does not publish MQTT directly; the bridge does the encoding.

## Decision
Use JSON with `schema_version`, JSON Schemas in the repo, ignore-unknown-fields consumers, and a documented compatibility policy. Parse with typed deserialization in Rust. Keep MCU↔bridge frames binary and compact.

## Alternatives considered
- Protobuf/CBOR from day one: smaller and faster, harder to inspect and evolve by hand.
- Schema registry: overkill at this stage.

## Consequences
+ Easy to inspect with `mosquitto_sub`; simple contracts and tests.
− Larger payloads and higher CPU per message.
Mitigation: measure parsing cost and bytes per message in benchmarks; the versioning policy allows a v2 binary format.

## Revisit when
Ingest CPU profile is dominated by JSON parsing or network bytes become a bottleneck (benchmark result decides).
