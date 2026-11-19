# ADR-0009: Tenant isolation with identity-derived tenant and PostgreSQL RLS
Status: Accepted · Date: 2026-11-13

## Context
Multi-tenancy bugs typically come from a missing filter. Tenant data may also be supplied by untrusted inputs (topics, payloads, LLM tool arguments).

## Decision
- The tenant always comes from the authenticated principal (user session, device registry lookup by MQTT identity, agent run token), never from request bodies, topics, or model output.
- `tenant_id` on every tenant-owned row; PostgreSQL RLS with `SET LOCAL app.tenant_id` per transaction; the app role lacks `BYPASSRLS`.
- ClickHouse access through a tenant-scoped query builder plus row policies; vector retrieval filters by tenant.
- A cross-tenant test suite runs in CI.

## Alternatives considered
- Schema or database per tenant: strong isolation, heavy operations.
- Application-level filtering only: fragile.
- Tenant in MQTT topics: easy routing but lets a compromised device attempt cross-tenant publishes if ACLs are wrong.

## Consequences
+ Defense in depth with testable guarantees.
− RLS adds query planning considerations and needs careful role management and connection pooling (`SET LOCAL` inside transactions).
Mitigation: benchmarks with RLS on; transaction-mode pooling rules documented.

## Revisit when
Per-tenant data volume or compliance needs justify physical separation.
