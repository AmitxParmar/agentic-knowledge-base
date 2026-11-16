//! Tracing setup shared by the binaries.

use tracing_subscriber::{fmt, EnvFilter};

pub fn init(service: &'static str) {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new(format!("info,devicehub_hub=info,{service}=debug")));

    fmt().with_env_filter(filter).with_target(true).init();
}
