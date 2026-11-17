//! MQTT ingest and the heartbeat/retention sweeps.
//!
//! Validation happens here, in Rust, before anything is stored. The broker
//! only authenticates; it never decides what a message means.

use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use devicehub_common::wire::{clamp_ts, parse_status, parse_telemetry, Reject};
use devicehub_common::Settings;
use rumqttc::{AsyncClient, Event, MqttOptions, Packet, QoS, Transport};
use serde_json::json;
use sqlx::PgPool;
use tokio::sync::broadcast;
use uuid::Uuid;

use crate::state::{DeviceStateEvent, Stats};

const BROKER_RETRY_DELAY: Duration = Duration::from_secs(2);
const HEARTBEAT_SWEEP: Duration = Duration::from_secs(5);
const RETENTION_SWEEP: Duration = Duration::from_secs(3600);

pub async fn run(
    settings: Settings,
    db: PgPool,
    events: broadcast::Sender<DeviceStateEvent>,
    stats: Arc<Stats>,
) -> anyhow::Result<()> {
    let sweeper = tokio::spawn(sweep_loop(settings.clone(), db.clone(), events.clone()));
    let result = ingest_loop(&settings, &db, &events, &stats).await;
    sweeper.abort();
    result
}

async fn ingest_loop(
    settings: &Settings,
    db: &PgPool,
    events: &broadcast::Sender<DeviceStateEvent>,
    stats: &Stats,
) -> anyhow::Result<()> {
    let mut options = MqttOptions::new(
        settings.mqtt_client_id.clone(),
        settings.mqtt_host.clone(),
        settings.mqtt_port,
    );
    options.set_keep_alive(Duration::from_secs(15));
    options.set_clean_session(true);
    if let (Some(username), Some(password)) = (&settings.mqtt_username, &settings.mqtt_password) {
        options.set_credentials(username.clone(), password.clone());
    }
    if settings.mqtt_tls {
        // System trust roots; cloud brokers use a public CA.
        options.set_transport(Transport::tls_with_default_config());
    }

    let (client, mut eventloop) = AsyncClient::new(options, 64);
    let telemetry_topic = format!("{}/d/+/telemetry", settings.mqtt_topic_prefix);
    let status_topic = format!("{}/d/+/status", settings.mqtt_topic_prefix);

    tracing::info!(
        host = %settings.mqtt_host,
        port = settings.mqtt_port,
        "subscribing to device topics"
    );

    loop {
        match eventloop.poll().await {
            Ok(Event::Incoming(Packet::ConnAck(_))) => {
                // clean_session=true means subscriptions do not survive a
                // reconnect, so they are re-sent on every ConnAck.
                for topic in [&telemetry_topic, &status_topic] {
                    match client.subscribe(topic.clone(), QoS::AtLeastOnce).await {
                        Ok(()) => tracing::info!(%topic, "subscribed"),
                        Err(err) => tracing::error!(%err, %topic, "subscribe failed"),
                    }
                }
            }
            Ok(Event::Incoming(Packet::Publish(publish))) => {
                match parse_topic(&settings.mqtt_topic_prefix, &publish.topic) {
                    Some((device_id, "telemetry")) => {
                        if let Err(err) = handle_telemetry(
                            db,
                            events,
                            stats,
                            &publish.topic,
                            device_id,
                            &publish.payload,
                        )
                        .await
                        {
                            tracing::error!(%err, %device_id, "telemetry handling failed");
                        }
                    }
                    Some((device_id, "status")) => {
                        if let Err(err) = handle_status(
                            db,
                            events,
                            stats,
                            &publish.topic,
                            device_id,
                            &publish.payload,
                        )
                        .await
                        {
                            tracing::error!(%err, %device_id, "status handling failed");
                        }
                    }
                    Some((_, other)) => tracing::debug!(kind = other, "ignoring topic"),
                    None => tracing::debug!(topic = %publish.topic, "ignoring unparsed topic"),
                }
            }
            Ok(_) => {}
            Err(err) => {
                tracing::warn!(%err, "mqtt connection lost; retrying");
                tokio::time::sleep(BROKER_RETRY_DELAY).await;
            }
        }
    }
}

fn parse_topic<'a>(prefix: &str, topic: &'a str) -> Option<(Uuid, &'a str)> {
    let rest = topic.strip_prefix(prefix)?.strip_prefix("/d/")?;
    let (id, kind) = rest.split_once('/')?;
    Some((Uuid::parse_str(id).ok()?, kind))
}

async fn handle_telemetry(
    db: &PgPool,
    events: &broadcast::Sender<DeviceStateEvent>,
    stats: &Stats,
    topic: &str,
    topic_device: Uuid,
    raw: &[u8],
) -> Result<(), sqlx::Error> {
    let telemetry = match parse_telemetry(topic_device, raw) {
        Ok(telemetry) => telemetry,
        Err(reject) => {
            dead_letter(db, stats, topic, Some(topic_device), reject, raw).await;
            return Ok(());
        }
    };

    let tenant_id =
        match sqlx::query_scalar::<_, Uuid>("select tenant_id from core.device where id = $1")
            .bind(topic_device)
            .fetch_optional(db)
            .await?
        {
            Some(tenant_id) => tenant_id,
            None => {
                dead_letter(
                    db,
                    stats,
                    topic,
                    Some(topic_device),
                    Reject::new("unknown_device", "device id is not registered"),
                    raw,
                )
                .await;
                return Ok(());
            }
        };

    let now = Utc::now();
    let (ts, clock_skew) = clamp_ts(telemetry.ts, now);
    let payload = serde_json::to_value(&telemetry).unwrap_or_else(|_| json!({}));

    let previous = sqlx::query_as::<_, (Uuid, i64)>(
        "select boot_id, last_seq from core.device_latest_state where device_id = $1",
    )
    .bind(topic_device)
    .fetch_optional(db)
    .await?;

    if let Some((boot_id, last_seq)) = previous {
        if boot_id == telemetry.boot_id && i64::from(telemetry.seq) > last_seq + 1 {
            stats.add_gap((i64::from(telemetry.seq) - last_seq - 1) as u64);
        }
    }

    let inserted = sqlx::query_scalar::<_, i64>(
        r#"
        insert into core.telemetry_event
            (tenant_id, device_id, boot_id, seq, ts, schema_version, fw_version,
             distance_cm, line_l, line_c, line_r, motion_state, left_pwm, right_pwm,
             battery_mv, config_version, clock_skew, payload)
        values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
        on conflict (device_id, boot_id, seq) do nothing
        returning id
        "#,
    )
    .bind(tenant_id)
    .bind(topic_device)
    .bind(telemetry.boot_id)
    .bind(i64::from(telemetry.seq))
    .bind(ts)
    .bind(i32::from(telemetry.schema_version))
    .bind(telemetry.fw_version.clone())
    .bind(telemetry.distance_cm)
    .bind(telemetry.line.map(|line| line.l))
    .bind(telemetry.line.and_then(|line| line.c))
    .bind(telemetry.line.map(|line| line.r))
    .bind(telemetry.motion_state())
    .bind(telemetry.motion.and_then(|motion| motion.left_pwm))
    .bind(telemetry.motion.and_then(|motion| motion.right_pwm))
    .bind(telemetry.battery_mv())
    .bind(telemetry.config_version)
    .bind(clock_skew)
    .bind(&payload)
    .fetch_optional(db)
    .await?;

    sqlx::query("update core.device set status = 'online', last_seen_at = now() where id = $1")
        .bind(topic_device)
        .execute(db)
        .await?;

    let Some(event_id) = inserted else {
        stats.incr_duplicate();
        tracing::debug!(%topic_device, seq = telemetry.seq, "duplicate telemetry dropped");
        return Ok(());
    };

    // Latest state only moves forward: higher seq in the same boot, or a newer
    // timestamp across boots. History keeps every accepted event.
    sqlx::query(
        r#"
        insert into core.device_latest_state
            (device_id, tenant_id, boot_id, last_seq, last_event_ts, telemetry, online, updated_at)
        values ($1,$2,$3,$4,$5,$6,true,now())
        on conflict (device_id) do update set
            boot_id = excluded.boot_id,
            last_seq = excluded.last_seq,
            last_event_ts = excluded.last_event_ts,
            telemetry = excluded.telemetry,
            online = true,
            updated_at = now()
        where core.device_latest_state.boot_id is null
           or (excluded.boot_id = core.device_latest_state.boot_id
               and excluded.last_seq > core.device_latest_state.last_seq)
           or (excluded.boot_id <> core.device_latest_state.boot_id
               and excluded.last_event_ts > core.device_latest_state.last_event_ts)
        "#,
    )
    .bind(topic_device)
    .bind(tenant_id)
    .bind(telemetry.boot_id)
    .bind(i64::from(telemetry.seq))
    .bind(ts)
    .bind(&payload)
    .execute(db)
    .await?;

    stats.incr_accepted();
    let _ = events.send(DeviceStateEvent {
        id: Some(event_id),
        device_id: topic_device,
        ts,
        online: Some(true),
        payload,
    });

    Ok(())
}

async fn handle_status(
    db: &PgPool,
    events: &broadcast::Sender<DeviceStateEvent>,
    stats: &Stats,
    topic: &str,
    topic_device: Uuid,
    raw: &[u8],
) -> Result<(), sqlx::Error> {
    let status = match parse_status(raw) {
        Ok(status) => status,
        Err(reject) => {
            dead_letter(db, stats, topic, Some(topic_device), reject, raw).await;
            return Ok(());
        }
    };

    let updated = sqlx::query_scalar::<_, Uuid>(
        "update core.device set status = $2, last_seen_at = now() where id = $1 returning id",
    )
    .bind(topic_device)
    .bind(if status.state.is_online() {
        "online"
    } else {
        "offline"
    })
    .fetch_optional(db)
    .await?;

    if updated.is_none() {
        dead_letter(
            db,
            stats,
            topic,
            Some(topic_device),
            Reject::new("unknown_device", "device id is not registered"),
            raw,
        )
        .await;
        return Ok(());
    }

    if !status.state.is_online() {
        sqlx::query("update core.device_latest_state set online = false where device_id = $1")
            .bind(topic_device)
            .execute(db)
            .await?;
    }

    let _ = events.send(DeviceStateEvent {
        id: None,
        device_id: topic_device,
        ts: status.ts.unwrap_or_else(Utc::now),
        online: Some(status.state.is_online()),
        payload: serde_json::to_value(&status).unwrap_or_else(|_| json!({})),
    });

    Ok(())
}

async fn dead_letter(
    db: &PgPool,
    stats: &Stats,
    topic: &str,
    device_id: Option<Uuid>,
    reject: Reject,
    raw: &[u8],
) {
    stats.incr_dead_letter();
    tracing::warn!(reason = reject.reason, detail = %reject.detail, %topic, "message rejected");

    if let Err(err) = sqlx::query(
        r#"
        insert into core.dead_letter (source, topic, device_id, reason, raw)
        values ($1,$2,$3,$4,$5)
        "#,
    )
    .bind("mqtt")
    .bind(topic)
    .bind(device_id)
    .bind(reject.reason)
    .bind(raw)
    .execute(db)
    .await
    {
        tracing::error!(%err, "failed to record dead letter");
    }
}

async fn sweep_loop(settings: Settings, db: PgPool, events: broadcast::Sender<DeviceStateEvent>) {
    let mut heartbeat = tokio::time::interval(HEARTBEAT_SWEEP);
    let mut retention = tokio::time::interval(RETENTION_SWEEP);
    // Both intervals tick once immediately; retention should not run on boot.
    retention.tick().await;

    loop {
        tokio::select! {
            _ = heartbeat.tick() => {
                if let Err(err) = mark_offline(&settings, &db, &events).await {
                    tracing::error!(%err, "offline sweep failed");
                }
            }
            _ = retention.tick() => {
                match sqlx::query(
                    "delete from core.telemetry_event where ingested_at < now() - make_interval(hours => $1)",
                )
                .bind(settings.telemetry_retention_hours)
                .execute(&db)
                .await
                {
                    Ok(result) => tracing::info!(deleted = result.rows_affected(), "retention sweep"),
                    Err(err) => tracing::error!(%err, "retention sweep failed"),
                }
            }
        }
    }
}

async fn mark_offline(
    settings: &Settings,
    db: &PgPool,
    events: &broadcast::Sender<DeviceStateEvent>,
) -> Result<(), sqlx::Error> {
    let stale = sqlx::query_scalar::<_, Uuid>(
        r#"
        update core.device
        set status = 'offline'
        where status = 'online'
          and (last_seen_at is null
               or last_seen_at < now() - make_interval(secs => $1))
        returning id
        "#,
    )
    .bind(settings.heartbeat_timeout_secs as f64)
    .fetch_all(db)
    .await?;

    if stale.is_empty() {
        return Ok(());
    }

    sqlx::query("update core.device_latest_state set online = false where device_id = any($1)")
        .bind(&stale)
        .execute(db)
        .await?;

    for device_id in stale {
        tracing::info!(%device_id, "device marked offline after heartbeat timeout");
        let _ = events.send(DeviceStateEvent {
            id: None,
            device_id,
            ts: Utc::now(),
            online: Some(false),
            payload: json!({ "state": "offline", "reason": "heartbeat_timeout" }),
        });
    }

    Ok(())
}
