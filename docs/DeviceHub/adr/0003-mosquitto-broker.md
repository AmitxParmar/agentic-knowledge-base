# ADR-0003: Mosquitto as the MQTT broker (EMQX as migration path)
Status: Accepted · Date: 2026-11-13

## Context
The plan allows Mosquitto or EMQX. Needs: per-device ACLs, TLS, QoS 1, retained messages, last will, shared subscriptions, easy local Compose setup.

## Decision
Use Mosquitto for the MVP. Device identity is the MQTT username `d_<device_id>`, with pattern ACLs (`%u`) restricting each device to its own topics. `hub-worker` regenerates the password file from `core.device_credential` and reloads the broker. The tenant is not in topics (see ADR-0009).

## Alternatives considered
- EMQX: HTTP/DB authentication and ACL hooks, dashboard, clustering, rule engine. More capable, heavier to run and learn; pulls logic into the broker.
- Managed broker: removes local control and complicates offline development.

## Consequences
+ Small footprint, simple Compose, well-known behavior.
− Credential sync is a custom job with a propagation delay; no built-in clustering.
Mitigation: force-disconnect on revoke; document sync interval; keep broker access behind a small interface so a swap is feasible.

## Revisit when
Credential propagation delay, throughput, or clustering needs justify EMQX. Benchmark both as a stretch task (PROJECT_SCOPE P2).
