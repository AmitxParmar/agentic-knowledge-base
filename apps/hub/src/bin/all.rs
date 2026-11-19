//! Single-process deployment used on Render's free tier (ADR-0014).
//!
//! The logical API/worker split is unchanged; they are simply two Tokio tasks
//! on a current-thread runtime to stay inside the free instance's CPU budget.

use std::sync::Arc;

use devicehub_common::Settings;
use devicehub_hub::{api, db, state::AppState, state::Stats, telemetry, worker};
use tokio::sync::broadcast;

#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    telemetry::init("devicehub_hub::all");

    let settings = Arc::new(Settings::from_env()?);
    let pool = db::connect(&settings).await?;
    db::migrate(&pool).await?;

    let (events, _) = broadcast::channel(1024);
    let stats = Arc::new(Stats::default());
    let state = AppState::new(
        pool.clone(),
        Arc::clone(&settings),
        events.clone(),
        Arc::clone(&stats),
    );

    let api_task = tokio::spawn(api::serve(state, api::shutdown_signal()));
    let worker_task = tokio::spawn(worker::run(
        (*settings).clone(),
        pool,
        events,
        Arc::clone(&stats),
    ));

    tokio::select! {
        result = api_task => {
            tracing::info!("api stopped");
            result??;
        }
        result = worker_task => {
            tracing::error!("worker stopped unexpectedly");
            result??;
        }
    }

    Ok(())
}
