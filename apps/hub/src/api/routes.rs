//! Read endpoints. All queries are tenant-agnostic in Phase 2 because there
//! is exactly one seeded tenant; the columns are already tenant-scoped so the
//! next phase does not need a migration.

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::IntoResponse,
    Json,
};
use chrono::{DateTime, Utc};
use devicehub_common::wire::MAX_TELEMETRY_BYTES;
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

use crate::state::AppState;

const DEFAULT_LIMIT: i64 = 200;
const MAX_LIMIT: i64 = 500;

#[derive(Debug, Serialize, FromRow)]
pub struct DeviceSummary {
    pub id: Uuid,
    pub external_id: String,
    pub name: String,
    pub kind: String,
    pub model: Option<String>,
    pub fw_version: Option<String>,
    pub status: String,
    pub last_seen_at: Option<DateTime<Utc>>,
    pub online: bool,
    pub telemetry: Option<serde_json::Value>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Serialize, FromRow)]
pub struct TelemetryRow {
    pub id: i64,
    pub device_id: Uuid,
    pub boot_id: Uuid,
    pub seq: i64,
    pub ts: DateTime<Utc>,
    pub ingested_at: DateTime<Utc>,
    pub distance_cm: Option<f64>,
    pub line_l: Option<i32>,
    pub line_c: Option<i32>,
    pub line_r: Option<i32>,
    pub motion_state: Option<String>,
    pub left_pwm: Option<i32>,
    pub right_pwm: Option<i32>,
    pub battery_mv: Option<i32>,
    pub config_version: Option<i32>,
    pub clock_skew: bool,
    pub payload: serde_json::Value,
}

const DEVICE_QUERY: &str = r#"
    select d.id,
           d.external_id,
           d.name,
           d.kind,
           d.model,
           d.fw_version,
           d.status,
           d.last_seen_at,
           coalesce(s.updated_at > now() - make_interval(secs => $1), false) as online,
           s.telemetry,
           s.updated_at
    from core.device d
    left join core.device_latest_state s on s.device_id = d.id
"#;

pub async fn healthz() -> impl IntoResponse {
    (StatusCode::OK, Json(serde_json::json!({ "status": "ok" })))
}

pub async fn readyz(State(state): State<AppState>) -> impl IntoResponse {
    match sqlx::query_scalar::<_, i32>("select 1")
        .fetch_one(&state.db)
        .await
    {
        Ok(_) => (
            StatusCode::OK,
            Json(serde_json::json!({ "status": "ready" })),
        ),
        Err(err) => {
            tracing::error!(%err, "readiness probe failed");
            (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(serde_json::json!({
                    "status": "degraded",
                    "database": "unreachable"
                })),
            )
        }
    }
}

pub async fn list_devices(State(state): State<AppState>) -> impl IntoResponse {
    let sql = format!("{DEVICE_QUERY} order by d.external_id");

    match sqlx::query_as::<_, DeviceSummary>(&sql)
        .bind(state.settings.heartbeat_timeout_secs as f64)
        .fetch_all(&state.db)
        .await
    {
        Ok(devices) => (StatusCode::OK, Json(devices)).into_response(),
        Err(err) => internal_error(err),
    }
}

pub async fn get_device(State(state): State<AppState>, Path(id): Path<Uuid>) -> impl IntoResponse {
    let sql = format!("{DEVICE_QUERY} where d.id = $2");

    match sqlx::query_as::<_, DeviceSummary>(&sql)
        .bind(state.settings.heartbeat_timeout_secs as f64)
        .bind(id)
        .fetch_optional(&state.db)
        .await
    {
        Ok(Some(device)) => (StatusCode::OK, Json(device)).into_response(),
        Ok(None) => not_found("device_not_found"),
        Err(err) => internal_error(err),
    }
}

#[derive(Debug, Deserialize)]
pub struct TelemetryQuery {
    pub limit: Option<i64>,
    pub from: Option<DateTime<Utc>>,
    pub to: Option<DateTime<Utc>>,
}

pub async fn list_telemetry(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
    Query(query): Query<TelemetryQuery>,
) -> impl IntoResponse {
    let exists =
        sqlx::query_scalar::<_, bool>("select exists(select 1 from core.device where id = $1)")
            .bind(id)
            .fetch_one(&state.db)
            .await;

    match exists {
        Ok(true) => {}
        Ok(false) => return not_found("device_not_found"),
        Err(err) => return internal_error(err),
    }

    let limit = query.limit.unwrap_or(DEFAULT_LIMIT).clamp(1, MAX_LIMIT);

    let rows = sqlx::query_as::<_, TelemetryRow>(
        r#"
        select id, device_id, boot_id, seq, ts, ingested_at,
               distance_cm, line_l, line_c, line_r,
               motion_state, left_pwm, right_pwm,
               battery_mv, config_version, clock_skew, payload
        from core.telemetry_event
        where device_id = $1
          and ($2::timestamptz is null or ts >= $2)
          and ($3::timestamptz is null or ts <= $3)
        order by ts desc, seq desc
        limit $4
        "#,
    )
    .bind(id)
    .bind(query.from)
    .bind(query.to)
    .bind(limit)
    .fetch_all(&state.db)
    .await;

    match rows {
        Ok(rows) => (StatusCode::OK, Json(rows)).into_response(),
        Err(err) => internal_error(err),
    }
}

pub async fn stats(State(state): State<AppState>) -> impl IntoResponse {
    let snapshot = state.stats.snapshot();
    (
        StatusCode::OK,
        Json(serde_json::json!({
            "counters": snapshot,
            "limits": {
                "telemetry_payload_bytes": MAX_TELEMETRY_BYTES,
                "heartbeat_timeout_secs": state.settings.heartbeat_timeout_secs,
                "telemetry_retention_hours": state.settings.telemetry_retention_hours,
            }
        })),
    )
}

fn not_found(code: &str) -> axum::response::Response {
    (
        StatusCode::NOT_FOUND,
        Json(serde_json::json!({ "error": code })),
    )
        .into_response()
}

fn internal_error(err: sqlx::Error) -> axum::response::Response {
    tracing::error!(%err, "database query failed");
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(serde_json::json!({ "error": "internal_error" })),
    )
        .into_response()
}
