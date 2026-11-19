//! Demo bearer-token check.
//!
//! This is *not* the `SECURITY.md` user-authentication design: there are no
//! users, sessions, or tenants in Phase 2. It exists so the read API is not
//! world-readable during the demo, and it must be replaced before anything
//! is exposed beyond a portfolio demo.

use axum::{
    extract::{Request, State},
    http::{header, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
};

use crate::state::AppState;

pub async fn require_token(
    State(state): State<AppState>,
    request: Request,
    next: Next,
) -> Response {
    let presented = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "));

    match presented {
        Some(token) if token == state.settings.api_token => next.run(request).await,
        Some(_) => (StatusCode::FORBIDDEN, "invalid token").into_response(),
        None => (StatusCode::UNAUTHORIZED, "missing bearer token").into_response(),
    }
}
