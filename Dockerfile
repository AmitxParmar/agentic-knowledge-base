# DeviceHub hub — single-process deployment (ADR-0014).
#
# One binary runs the read API and the MQTT ingest worker (`--bin all`), which
# is the only shape a Render free web service can host: no background workers,
# one HTTP port, outbound TLS for Neon and the cloud broker.
#
# Build context is the repo root because Cargo resolves the whole workspace.
#   docker build -t devicehub-hub .
#   docker run --rm -p 8080:8080 --env-file apps/hub/.env devicehub-hub

FROM rust:1-slim-bookworm AS builder

# The workspace release profile uses thin LTO and one codegen unit. That is
# right for a local build and too heavy for a 512 MB build container, so the
# env overrides trade a little binary size for a build that finishes.
ENV CARGO_TERM_COLOR=never \
    CARGO_PROFILE_RELEASE_LTO=false \
    CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16

WORKDIR /src

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY Cargo.toml Cargo.lock ./
COPY crates/common ./crates/common
COPY apps/hub ./apps/hub
# Copied only so the workspace manifest parses; never built (libudev).
COPY apps/bridge ./apps/bridge

RUN cargo build --release -p devicehub-hub --bin all

FROM debian:bookworm-slim AS runtime

# ca-certificates is required: Neon uses TLS, and MQTT_TLS uses the system roots.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home devicehub

WORKDIR /app
COPY --from=builder /src/target/release/all /app/all

USER devicehub

# Render sets PORT; Settings::from_env reads it and binds 0.0.0.0 by default.
ENV PORT=8080
EXPOSE 8080

CMD ["/app/all"]
