//! Database pool and migrations.

use std::time::Duration;

use devicehub_common::Settings;
use sqlx::postgres::{PgPool, PgPoolOptions};

pub async fn connect(settings: &Settings) -> Result<PgPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(settings.db_max_connections)
        .acquire_timeout(Duration::from_secs(5))
        .connect(&settings.database_url)
        .await
}

/// Apply embedded migrations. Safe to run on every boot, and on both the
/// API and the worker, because SQLx takes an advisory lock.
pub async fn migrate(pool: &PgPool) -> Result<(), sqlx::migrate::MigrateError> {
    sqlx::migrate!("./migrations").run(pool).await
}
