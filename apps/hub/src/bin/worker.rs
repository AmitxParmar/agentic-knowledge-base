use std::sync::Arc;

use devicehub_common::Settings;
use devicehub_hub::state::Stats;
use devicehub_hub::{db, telemetry, worker};
use tokio::sync::broadcast;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    telemetry::init("devicehub_hub::worker");

    let settings = Settings::from_env()?;
    let pool = db::connect(&settings).await?;
    db::migrate(&pool).await?;

    let (events, _) = broadcast::channel(1024);
    worker::run(settings, pool, events, Arc::new(Stats::default())).await
}
