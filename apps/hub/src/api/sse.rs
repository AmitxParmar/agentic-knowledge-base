//! Server-sent events.
//!
//! Two behaviours matter for the demo:
//! * a keepalive every 15 s, because Render's proxy closes idle connections;
//! * replay after `Last-Event-ID`, so a reconnect does not leave a hole.

use std::convert::Infallible;
use std::time::Duration;

use axum::{
    extract::State,
    http::HeaderMap,
    response::sse::{Event, KeepAlive, Sse},
};
use chrono::{DateTime, Utc};
use futures_core::Stream;
use uuid::Uuid;

use crate::state::{AppState, DeviceStateEvent};

const REPLAY_LIMIT: i64 = 100;

pub async fn stream(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    // Subscribe before replaying so events that arrive during the query are
    // queued rather than lost. The client dedupes by event id.
    let mut receiver = state.events.subscribe();
    let last_id = last_event_id(&headers);

    let replay = match last_id {
        Some(id) => fetch_after(&state, id).await,
        None => Vec::new(),
    };

    let stream = async_stream::stream! {
        for event in replay {
            yield Ok(to_sse_event(&event));
        }

        loop {
            match receiver.recv().await {
                Ok(event) => yield Ok(to_sse_event(&event)),
                Err(tokio::sync::broadcast::error::RecvError::Lagged(skipped)) => {
                    tracing::warn!(skipped, "sse subscriber lagged; continuing");
                    continue;
                }
                Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
            }
        }
    };

    Sse::new(stream).keep_alive(
        KeepAlive::new()
            .interval(Duration::from_secs(15))
            .text("keepalive"),
    )
}

fn last_event_id(headers: &HeaderMap) -> Option<i64> {
    headers
        .get("last-event-id")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.trim().parse::<i64>().ok())
}

async fn fetch_after(state: &AppState, last_id: i64) -> Vec<DeviceStateEvent> {
    let rows = sqlx::query_as::<_, (i64, Uuid, DateTime<Utc>, serde_json::Value)>(
        r#"
        select id, device_id, ts, payload
        from core.telemetry_event
        where id > $1
        order by id asc
        limit $2
        "#,
    )
    .bind(last_id)
    .bind(REPLAY_LIMIT)
    .fetch_all(&state.db)
    .await;

    match rows {
        Ok(rows) => rows
            .into_iter()
            .map(|(id, device_id, ts, payload)| DeviceStateEvent {
                id: Some(id),
                device_id,
                ts,
                online: None,
                payload,
            })
            .collect(),
        Err(err) => {
            tracing::error!(%err, "sse replay query failed");
            Vec::new()
        }
    }
}

fn to_sse_event(event: &DeviceStateEvent) -> Event {
    let data = serde_json::to_string(event).unwrap_or_else(|_| "{}".to_string());
    let mut sse = Event::default().event("device.state").data(data);
    if let Some(id) = event.id {
        sse = sse.id(id.to_string());
    }
    sse
}
