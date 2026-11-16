//! Shared process state and in-memory counters.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use chrono::{DateTime, Utc};
use devicehub_common::Settings;
use serde::Serialize;
use sqlx::PgPool;
use tokio::sync::broadcast;
use uuid::Uuid;

/// One update pushed to connected browsers.
#[derive(Debug, Clone, Serialize)]
pub struct DeviceStateEvent {
    /// Telemetry event id, used as the SSE event id for replay. `None` for
    /// status and sweep events, which are not replayable.
    pub id: Option<i64>,
    pub device_id: Uuid,
    pub ts: DateTime<Utc>,
    /// `None` means "historical replay"; the client should not infer presence.
    pub online: Option<bool>,
    pub payload: serde_json::Value,
}

#[derive(Default, Debug)]
pub struct Stats {
    pub accepted: AtomicU64,
    pub duplicates: AtomicU64,
    pub gaps: AtomicU64,
    pub dead_letters: AtomicU64,
}

#[derive(Debug, Clone, Copy, Serialize)]
pub struct StatsSnapshot {
    pub accepted: u64,
    pub duplicates: u64,
    pub gaps: u64,
    pub dead_letters: u64,
}

impl Stats {
    pub fn snapshot(&self) -> StatsSnapshot {
        StatsSnapshot {
            accepted: self.accepted.load(Ordering::Relaxed),
            duplicates: self.duplicates.load(Ordering::Relaxed),
            gaps: self.gaps.load(Ordering::Relaxed),
            dead_letters: self.dead_letters.load(Ordering::Relaxed),
        }
    }

    pub fn incr_accepted(&self) {
        self.accepted.fetch_add(1, Ordering::Relaxed);
    }

    pub fn incr_duplicate(&self) {
        self.duplicates.fetch_add(1, Ordering::Relaxed);
    }

    pub fn add_gap(&self, missing: u64) {
        self.gaps.fetch_add(missing, Ordering::Relaxed);
    }

    pub fn incr_dead_letter(&self) {
        self.dead_letters.fetch_add(1, Ordering::Relaxed);
    }
}

#[derive(Clone)]
pub struct AppState {
    pub db: PgPool,
    pub settings: Arc<Settings>,
    pub events: broadcast::Sender<DeviceStateEvent>,
    pub stats: Arc<Stats>,
}

impl AppState {
    pub fn new(
        db: PgPool,
        settings: Arc<Settings>,
        events: broadcast::Sender<DeviceStateEvent>,
        stats: Arc<Stats>,
    ) -> Self {
        Self {
            db,
            settings,
            events,
            stats,
        }
    }
}
