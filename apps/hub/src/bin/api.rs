use std::sync::Arc;

use devicehub_common::Settings;
use devicehub_hub::{api, db, state::AppState, state::Stats, telemetry};
use tokio::sync::broadcast;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    telemetry::init("devicehub_hub::api");

    let settings = Settings::from_env()?;
    let pool = db::connect(&settings).await?;
    db::migrate(&pool).await?;

    let (events, _) = broadcast::channel(1024);
    let state = AppState::new(pool, Arc::new(settings), events, Arc::new(Stats::default()));

    api::serve(state, api::shutdown_signal()).await
}
