//! `devicehub-bridge`: Arduino serial JSON → MQTT telemetry.
//!
//! The board speaks newline-delimited JSON over USB; this process stamps the
//! contract envelope and publishes to `dh/v1/d/{device_id}/telemetry`.
//! Nothing here decides anything about the robot: Phase 2 is telemetry only.

mod config;
mod frame;
mod publisher;
mod serial;

use chrono::Utc;
use tokio::sync::mpsc;
use tracing::{info, warn};
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

use devicehub_common::TelemetryV1;

use crate::config::BridgeSettings;
use crate::frame::{Envelope, SerialFrame};
use crate::serial::LinkEvent;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let settings = BridgeSettings::from_env()?;
    info!(
        device = %settings.device_id,
        port = %settings.serial_port,
        topic = %settings.telemetry_topic(),
        "devicehub-bridge starting"
    );

    let (link_tx, mut link_rx) = mpsc::channel::<LinkEvent>(512);
    let (event_tx, event_rx) = mpsc::channel::<TelemetryV1>(1024);

    let _serial = serial::spawn(settings.clone(), link_tx);
    let publisher = tokio::spawn(publisher::run(event_rx, settings.clone()));

    let mut envelope = Envelope {
        device_id: settings.device_id,
        boot_id: Uuid::new_v4(),
        fw_version: settings.fw_version.clone(),
    };
    let mut rejected: u64 = 0;

    while let Some(event) = link_rx.recv().await {
        match event {
            LinkEvent::Opened => {
                envelope.boot_id = Uuid::new_v4();
                info!(boot_id = %envelope.boot_id, "serial session started");
            }
            LinkEvent::Lost => warn!("serial link lost; reconnecting"),
            LinkEvent::Line(line) => match SerialFrame::parse(&line) {
                Ok(frame) => {
                    if event_tx
                        .send(frame.into_telemetry(&envelope, Utc::now()))
                        .await
                        .is_err()
                    {
                        break;
                    }
                }
                Err(error) => {
                    rejected += 1;
                    if rejected == 1 || rejected % 100 == 0 {
                        warn!(%error, rejected, "rejected serial line");
                    }
                }
            },
        }
    }

    info!("serial input closed; waiting for publisher to finish");
    let _ = publisher.await;
    Ok(())
}
