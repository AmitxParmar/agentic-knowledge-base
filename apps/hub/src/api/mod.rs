//! HTTP surface: health, read endpoints, and the SSE stream.

mod auth;
mod routes;
pub mod sse;

use std::time::Duration;

use axum::{
    http::{header, HeaderValue, Method},
    middleware,
    routing::get,
    Router,
};
use tower_http::cors::{AllowOrigin, CorsLayer};
use tower_http::trace::TraceLayer;

use crate::state::AppState;

pub fn router(state: AppState) -> Router {
    let protected = Router::new()
        .route("/v1/devices", get(routes::list_devices))
        .route("/v1/devices/{id}", get(routes::get_device))
        .route("/v1/devices/{id}/telemetry", get(routes::list_telemetry))
        .route("/v1/stream", get(sse::stream))
        .route("/v1/stats", get(routes::stats))
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            auth::require_token,
        ));

    let origins: Vec<HeaderValue> = state
        .settings
        .cors_origins
        .iter()
        .filter_map(|origin| origin.parse().ok())
        .collect();

    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::list(origins))
        .allow_methods([Method::GET])
        .allow_headers([header::AUTHORIZATION, header::CONTENT_TYPE])
        .max_age(Duration::from_secs(600));

    Router::new()
        .route("/healthz", get(routes::healthz))
        .route("/readyz", get(routes::readyz))
        .merge(protected)
        .with_state(state)
        .layer(TraceLayer::new_for_http())
        .layer(cors)
}

pub async fn serve<F>(state: AppState, shutdown: F) -> anyhow::Result<()>
where
    F: std::future::Future<Output = ()> + Send + 'static,
{
    let bind = state.settings.bind;
    let listener = tokio::net::TcpListener::bind(bind).await?;
    tracing::info!(%bind, "hub api listening");

    axum::serve(listener, router(state))
        .with_graceful_shutdown(shutdown)
        .await?;

    Ok(())
}

/// Resolve on Ctrl-C or SIGTERM.
pub async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };

    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut signal) => {
                signal.recv().await;
            }
            Err(err) => {
                tracing::warn!(%err, "SIGTERM handler unavailable");
                std::future::pending::<()>().await;
            }
        }
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }

    tracing::info!("shutdown signal received");
}
