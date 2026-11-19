//! Wire contracts from `EVENT_CONTRACTS.md` §4 and §5.
//!
//! Parsing is intentionally permissive about unknown fields (the contract
//! requires consumers to ignore them) and strict about identity and version.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Payload schema version this build understands.
pub const SCHEMA_VERSION: u16 = 1;

/// `EVENT_CONTRACTS.md` §4 caps telemetry at 512 bytes.
pub const MAX_TELEMETRY_BYTES: usize = 512;

/// Beyond this distance from the receive time, `ts` is clamped to ingest time.
pub const CLOCK_SKEW_SECS: i64 = 300;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct LineSensors {
    pub l: i32,
    /// Absent on devices with two sensors (the Phase 2 bench device). Never
    /// inferred as zero.
    #[serde(default)]
    pub c: Option<i32>,
    pub r: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MotionState {
    Idle,
    Forward,
    TurnLeft,
    TurnRight,
    Stopped,
    Estop,
}

impl MotionState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Idle => "idle",
            Self::Forward => "forward",
            Self::TurnLeft => "turn_left",
            Self::TurnRight => "turn_right",
            Self::Stopped => "stopped",
            Self::Estop => "estop",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Motion {
    pub state: MotionState,
    #[serde(default)]
    pub left_pwm: Option<i32>,
    #[serde(default)]
    pub right_pwm: Option<i32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Power {
    #[serde(default)]
    pub battery_mv: Option<i32>,
}

/// `dh/v1/d/{id}/telemetry` payload.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TelemetryV1 {
    pub schema_version: u16,
    pub device_id: Uuid,
    pub boot_id: Uuid,
    pub seq: u32,
    pub ts: DateTime<Utc>,
    #[serde(default)]
    pub ts_mono_ms: Option<u32>,
    #[serde(default)]
    pub fw_version: Option<String>,
    #[serde(default)]
    pub distance_cm: Option<f64>,
    #[serde(default)]
    pub line: Option<LineSensors>,
    #[serde(default)]
    pub motion: Option<Motion>,
    #[serde(default)]
    pub power: Option<Power>,
    #[serde(default)]
    pub config_version: Option<i32>,
}

impl TelemetryV1 {
    pub fn motion_state(&self) -> Option<&'static str> {
        self.motion.map(|motion| motion.state.as_str())
    }

    pub fn battery_mv(&self) -> Option<i32> {
        self.power.and_then(|power| power.battery_mv)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeviceOnlineState {
    Online,
    Offline,
}

impl DeviceOnlineState {
    pub fn is_online(self) -> bool {
        matches!(self, Self::Online)
    }
}

/// `dh/v1/d/{id}/status` payload.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StatusV1 {
    pub schema_version: u16,
    pub state: DeviceOnlineState,
    #[serde(default)]
    pub boot_id: Option<Uuid>,
    #[serde(default)]
    pub fw_version: Option<String>,
    #[serde(default)]
    pub ts: Option<DateTime<Utc>>,
    #[serde(default)]
    pub reason: Option<String>,
}

/// Why a message was sent to `core.dead_letter`.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{reason}: {detail}")]
pub struct Reject {
    /// Stable, low-cardinality reason stored in the database.
    pub reason: &'static str,
    pub detail: String,
}

impl Reject {
    pub fn new(reason: &'static str, detail: impl Into<String>) -> Self {
        Self {
            reason,
            detail: detail.into(),
        }
    }
}

/// Parse and validate a telemetry payload against its topic identity.
pub fn parse_telemetry(topic_device: Uuid, payload: &[u8]) -> Result<TelemetryV1, Reject> {
    if payload.len() > MAX_TELEMETRY_BYTES {
        return Err(Reject::new(
            "oversize",
            format!("{} bytes exceeds {}", payload.len(), MAX_TELEMETRY_BYTES),
        ));
    }

    let telemetry: TelemetryV1 = serde_json::from_slice(payload)
        .map_err(|err| Reject::new("malformed_json", err.to_string()))?;

    if telemetry.schema_version != SCHEMA_VERSION {
        return Err(Reject::new(
            "unsupported_version",
            format!("schema_version {}", telemetry.schema_version),
        ));
    }

    if telemetry.device_id != topic_device {
        return Err(Reject::new(
            "identity_mismatch",
            format!(
                "topic device {} != payload device {}",
                topic_device, telemetry.device_id
            ),
        ));
    }

    if telemetry.seq == 0 {
        return Err(Reject::new("invalid_field", "seq must start at 1"));
    }

    if let Some(motion) = telemetry.motion {
        for pwm in [motion.left_pwm, motion.right_pwm].into_iter().flatten() {
            if !(-255..=255).contains(&pwm) {
                return Err(Reject::new(
                    "invalid_field",
                    format!("pwm {pwm} outside -255..=255"),
                ));
            }
        }
    }

    Ok(telemetry)
}

/// Parse a retained status payload.
pub fn parse_status(payload: &[u8]) -> Result<StatusV1, Reject> {
    let status: StatusV1 = serde_json::from_slice(payload)
        .map_err(|err| Reject::new("malformed_json", err.to_string()))?;

    if status.schema_version != SCHEMA_VERSION {
        return Err(Reject::new(
            "unsupported_version",
            format!("schema_version {}", status.schema_version),
        ));
    }

    Ok(status)
}

/// Clamp an implausible device clock to ingest time.
///
/// Returns the timestamp to store and whether it was adjusted.
pub fn clamp_ts(ts: DateTime<Utc>, now: DateTime<Utc>) -> (DateTime<Utc>, bool) {
    if (ts - now).num_seconds().abs() > CLOCK_SKEW_SECS {
        (now, true)
    } else {
        (ts, false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DEVICE: &str = "0192f3c4-1a2b-7c3d-8e4f-5a6b7c8d9e0f";

    fn payload(extra: &str) -> Vec<u8> {
        format!(
            r#"{{"schema_version":1,"device_id":"{DEVICE}","boot_id":"0192f3c4-0000-7000-8000-000000000001","seq":7,"ts":"2026-11-17T09:15:02.481Z","ts_mono_ms":921440,"fw_version":"0.1.0","distance_cm":23.4,"line":{{"l":120,"c":860,"r":130}},"motion":{{"state":"idle"}},"power":{{"battery_mv":7400}},"config_version":3{extra}}}"#
        )
        .into_bytes()
    }

    fn device() -> Uuid {
        DEVICE.parse().expect("device uuid")
    }

    #[test]
    fn parses_a_valid_payload() {
        let telemetry = parse_telemetry(device(), &payload("")).expect("valid");
        assert_eq!(telemetry.seq, 7);
        assert_eq!(telemetry.distance_cm, Some(23.4));
        assert_eq!(telemetry.motion_state(), Some("idle"));
        assert_eq!(telemetry.battery_mv(), Some(7400));
    }

    #[test]
    fn ignores_unknown_fields() {
        let telemetry = parse_telemetry(device(), &payload(r#","future_field":{"a":1}"#))
            .expect("unknown fields are allowed");
        assert_eq!(telemetry.seq, 7);
    }

    #[test]
    fn rejects_identity_mismatch() {
        let other = Uuid::nil();
        let err = parse_telemetry(other, &payload("")).unwrap_err();
        assert_eq!(err.reason, "identity_mismatch");
    }

    #[test]
    fn rejects_unsupported_version() {
        let body = String::from_utf8(payload(""))
            .unwrap()
            .replace(r#""schema_version":1"#, r#""schema_version":2"#);
        let err = parse_telemetry(device(), body.as_bytes()).unwrap_err();
        assert_eq!(err.reason, "unsupported_version");
    }

    #[test]
    fn rejects_malformed_json() {
        let err = parse_telemetry(device(), b"{not json").unwrap_err();
        assert_eq!(err.reason, "malformed_json");
    }

    #[test]
    fn rejects_oversize_payloads() {
        let body = vec![b' '; MAX_TELEMETRY_BYTES + 1];
        let err = parse_telemetry(device(), &body).unwrap_err();
        assert_eq!(err.reason, "oversize");
    }

    #[test]
    fn rejects_out_of_range_pwm() {
        let body = String::from_utf8(payload(""))
            .unwrap()
            .replace(r#""state":"idle""#, r#""state":"forward","left_pwm":900"#);
        let err = parse_telemetry(device(), body.as_bytes()).unwrap_err();
        assert_eq!(err.reason, "invalid_field");
    }

    #[test]
    fn clamps_skewed_clocks() {
        let now = Utc::now();
        let (kept, skew) = clamp_ts(now, now);
        assert!(!skew);
        assert_eq!(kept, now);

        let past = now - chrono::Duration::hours(2);
        let (stored, skew) = clamp_ts(past, now);
        assert!(skew);
        assert_eq!(stored, now);
    }

    #[test]
    fn accepts_two_sensor_devices() {
        let body = String::from_utf8(payload("")).unwrap().replace(
            r#""line":{"l":120,"c":860,"r":130}"#,
            r#""line":{"l":120,"r":130}"#,
        );
        let telemetry = parse_telemetry(device(), body.as_bytes()).expect("two sensors");
        let line = telemetry.line.expect("line block");
        assert_eq!(line.c, None);
        assert_eq!(line.r, 130);
    }

    #[test]
    fn parses_status() {
        let status = parse_status(
            br#"{"schema_version":1,"state":"offline","reason":"unclean_disconnect"}"#,
        )
        .expect("valid status");
        assert!(!status.state.is_online());
        assert_eq!(status.reason.as_deref(), Some("unclean_disconnect"));
    }
}
