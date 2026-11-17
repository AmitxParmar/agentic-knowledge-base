//! Publish queue and broker loop.
//!
//! Policy: an event is only removed from the local queue once the broker has
//! acknowledged it. While the broker is unreachable the queue keeps filling,
//! bounded by `BRIDGE_BUFFER_CAPACITY`; the oldest events are dropped first.
//! Original `seq` values are preserved, so replay after an outage is exactly
//! the same payload the device produced.

use std::collections::VecDeque;
use std::time::{Duration, Instant};

use rumqttc::{AsyncClient, Event, Incoming, MqttOptions, QoS};
use tokio::sync::mpsc;
use tracing::{info, warn};

use devicehub_common::TelemetryV1;

use crate::config::BridgeSettings;

const MAX_BACKOFF: Duration = Duration::from_secs(30);
const ACK_TIMEOUT: Duration = Duration::from_secs(15);

/// Push an event, dropping the oldest when full. Returns `true` if a drop happened.
pub fn enqueue(queue: &mut VecDeque<TelemetryV1>, event: TelemetryV1, capacity: usize) -> bool {
    if capacity == 0 {
        return true;
    }
    let mut dropped = false;
    while queue.len() >= capacity {
        queue.pop_front();
        dropped = true;
    }
    queue.push_back(event);
    dropped
}

pub async fn run(mut rx: mpsc::Receiver<TelemetryV1>, settings: BridgeSettings) {
    let topic = settings.telemetry_topic();
    let mut queue: VecDeque<TelemetryV1> = VecDeque::new();
    let mut dropped_total: u64 = 0;
    let mut backoff = Duration::from_secs(1);

    loop {
        let mut options = MqttOptions::new(
            &settings.mqtt_client_id,
            &settings.mqtt_host,
            settings.mqtt_port,
        );
        options.set_keep_alive(Duration::from_secs(30));
        if let Some(username) = &settings.mqtt_username {
            options.set_credentials(username, settings.mqtt_password.clone().unwrap_or_default());
        }

        let (client, mut eventloop) = AsyncClient::new(options, 8);
        let mut connected = false;
        // Timestamp of the in-flight publish, if any. The front of the queue
        // stays put until its PubAck arrives.
        let mut in_flight: Option<Instant> = None;
        let mut ticker = tokio::time::interval(Duration::from_secs(5));

        loop {
            tokio::select! {
                _ = ticker.tick() => {
                    if in_flight.is_some_and(|sent| sent.elapsed() > ACK_TIMEOUT) {
                        warn!("publish not acknowledged in time; republishing");
                        in_flight = None;
                    }
                }
                event = eventloop.poll() => {
                    match event {
                        Ok(Event::Incoming(Incoming::ConnAck(_))) => {
                            connected = true;
                            backoff = Duration::from_secs(1);
                            info!(%topic, queued = queue.len(), "broker connected");
                        }
                        Ok(Event::Incoming(Incoming::PubAck(_))) => {
                            in_flight = None;
                            queue.pop_front();
                        }
                        Ok(_) => {}
                        Err(error) => {
                            warn!(%error, queued = queue.len(), "broker connection lost");
                            break;
                        }
                    }
                }
                received = rx.recv() => {
                    let Some(event) = received else {
                        info!("serial input closed; bridge stopping");
                        return;
                    };
                    if enqueue(&mut queue, event, settings.buffer_capacity) {
                        dropped_total += 1;
                        if dropped_total == 1 || dropped_total % 100 == 0 {
                            warn!(
                                dropped = dropped_total,
                                capacity = settings.buffer_capacity,
                                "buffer full; oldest event dropped"
                            );
                        }
                    }
                }
            }

            // Publish the front event when connected and nothing is awaiting an ack.
            if connected && in_flight.is_none() {
                if let Some(next) = queue.front() {
                    let payload = match serde_json::to_vec(next) {
                        Ok(payload) => payload,
                        Err(error) => {
                            warn!(%error, "dropping unserialisable event");
                            queue.pop_front();
                            continue;
                        }
                    };
                    match client
                        .publish(&topic, QoS::AtLeastOnce, false, payload)
                        .await
                    {
                        Ok(()) => in_flight = Some(Instant::now()),
                        Err(error) => {
                            warn!(%error, "publish failed; will retry");
                            break;
                        }
                    }
                }
            }
        }

        info!(queued = queue.len(), "reconnecting");
        tokio::time::sleep(backoff).await;
        backoff = (backoff * 2).min(MAX_BACKOFF);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use uuid::Uuid;

    use devicehub_common::SCHEMA_VERSION;

    fn event(seq: u32) -> TelemetryV1 {
        TelemetryV1 {
            schema_version: SCHEMA_VERSION,
            device_id: Uuid::nil(),
            boot_id: Uuid::nil(),
            seq,
            ts: Utc::now(),
            ts_mono_ms: None,
            fw_version: None,
            distance_cm: None,
            line: None,
            motion: None,
            power: None,
            config_version: None,
        }
    }

    #[test]
    fn keeps_order_while_under_capacity() {
        let mut queue = VecDeque::new();
        assert!(!enqueue(&mut queue, event(1), 3));
        assert!(!enqueue(&mut queue, event(2), 3));
        assert!(!enqueue(&mut queue, event(3), 3));
        let seqs: Vec<u32> = queue.iter().map(|e| e.seq).collect();
        assert_eq!(seqs, vec![1, 2, 3]);
    }

    #[test]
    fn drops_the_oldest_when_full() {
        let mut queue = VecDeque::new();
        for seq in 1..=3 {
            enqueue(&mut queue, event(seq), 3);
        }
        assert!(enqueue(&mut queue, event(4), 3));
        let seqs: Vec<u32> = queue.iter().map(|e| e.seq).collect();
        assert_eq!(seqs, vec![2, 3, 4]);
    }

    #[test]
    fn zero_capacity_drops_everything() {
        let mut queue = VecDeque::new();
        assert!(enqueue(&mut queue, event(1), 0));
        assert!(queue.is_empty());
    }
}
