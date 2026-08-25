# ADR-008: JWT Authentication (HS256, PyJWT)

## Status

Accepted. Implements the maturity plan's "real auth" milestone
(`docs/superpowers/plans/2026-08-19-agentic-rag-maturity.md`, V2).
Amends the `PRD.md` Non-Goal "RBAC / Scoped Retrieval / Secret
Management" partially: authentication arrives now; roles/authorization
stay deferred.

## Context

Auth was a stub (`src/auth/stub.py`): fixed dev ids, `X-Workspace-Id`
header trusted blindly. Workspace scoping existed everywhere in queries,
but it was security-by-convention with no identity. The eval suite's
planned cross-workspace leak tests need real scoping to be meaningful.

PyJWT 2.13 is already resolved in the environment (transitive); HS256 is
a single shared-secret scheme appropriate for one self-hosted backend
with no third-party identity provider in scope.

## Decision

- **Library**: PyJWT, declared explicitly in `pyproject.toml`
  (`pyjwt>=2.8`). No new resolution.
- **Scheme**: HS256 symmetric. Secret lives in `AUTH_JWT_SECRET` env.
- **Modes** via `AUTH_MODE`:
  - `stub` (default): unchanged dev behavior — local runs and existing
    tests keep working with zero migration.
  - `jwt`: dependencies require `Authorization: Bearer`; failures are a
    generic 401 that never distinguishes expired vs malformed vs
    bad-signature.
- **Claims**: `sub` (user id), `ws` (workspace id), `iat`, `exp`.
  TTL via `AUTH_TOKEN_TTL` (default 12h).
- **Minting**: out-of-band operator CLI (`scripts/mint_token.py`) —
  refuses to run without the secret. No HTTP token endpoint until a
  login flow exists; auth-of-auth would add surface without value today.
- **Module shape**: dependency functions stay importable from
  `src.auth.stub` so every router import is untouched.

## Consequences

**Positives**

- Workspace scoping becomes enforced identity, not convention — leak
  tests can now assert isolation end-to-end.
- Zero-disruption rollout: flip `AUTH_MODE=jwt` per environment.
- No new dependency resolution; no external IdP integration.

**Negatives / accepted ceilings**

- **No RBAC**: any valid token grants full workspace access. Roles are
  deferred until multi-user demand exists.
- **Shared secret**: HS256 means every verifier holds minting power.
  Acceptable single-process; move to RS256/JWKS when a second service
  needs verification.
- **No refresh flow**: expired tokens require re-minting via CLI until
  a login UI ships.
