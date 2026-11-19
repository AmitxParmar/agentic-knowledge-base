-- DeviceHub core schema.
--
-- PostgreSQL only for the telemetry slice (ADR-0004). ClickHouse is a later
-- S2 addition; nothing here depends on it.
--
-- This schema is owned by the Rust device plane. The Knowledge Base's
-- `public` schema and its Alembic chain are untouched.

create schema if not exists core;

create table core.tenant (
    id uuid primary key,
    name text not null,
    created_at timestamptz not null default now()
);

create table core.device (
    id uuid primary key,
    tenant_id uuid not null references core.tenant (id),
    external_id text not null,
    name text not null,
    kind text not null check (kind in ('real', 'simulated')),
    model text,
    fw_version text,
    capabilities jsonb not null default '[]'::jsonb,
    status text not null default 'offline'
        check (status in ('online', 'offline', 'disabled')),
    last_seen_at timestamptz,
    created_at timestamptz not null default now(),
    unique (tenant_id, external_id)
);

create index device_status_idx on core.device (tenant_id, status);

create table core.device_latest_state (
    device_id uuid primary key references core.device (id) on delete cascade,
    tenant_id uuid not null,
    boot_id uuid,
    last_seq bigint,
    last_event_ts timestamptz,
    telemetry jsonb not null,
    online boolean not null default false,
    updated_at timestamptz not null default now()
);

-- Append-only history. The design puts this in ClickHouse at S2; PostgreSQL
-- carries it for the first slice, with retention enforced by the worker.
create table core.telemetry_event (
    id bigserial primary key,
    tenant_id uuid not null,
    device_id uuid not null references core.device (id) on delete cascade,
    boot_id uuid not null,
    seq bigint not null check (seq > 0),
    ts timestamptz not null,
    ingested_at timestamptz not null default now(),
    schema_version integer not null,
    fw_version text,
    distance_cm double precision,
    line_l integer,
    line_c integer,
    line_r integer,
    motion_state text,
    left_pwm integer,
    right_pwm integer,
    battery_mv integer,
    config_version integer,
    clock_skew boolean not null default false,
    payload jsonb not null,
    unique (device_id, boot_id, seq)
);

create index telemetry_event_device_ts_idx
    on core.telemetry_event (device_id, ts desc);

create index telemetry_event_retention_idx
    on core.telemetry_event (ingested_at);

create table core.dead_letter (
    id bigserial primary key,
    source text not null,
    topic text,
    device_id uuid,
    reason text not null,
    raw bytea not null,
    received_at timestamptz not null default now(),
    replayed_at timestamptz
);
