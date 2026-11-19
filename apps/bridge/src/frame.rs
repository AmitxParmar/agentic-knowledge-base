//! Serial frame parsing and envelope enrichment.
//!
//! The Arduino knows only what its own pins say. The bridge supplies the
//! identity and time fields the contract requires (`EVENT_CONTRACTS.md` §4):
//! `device_id`, `boot_id`, `ts`, `fw_version`, and `motion.state`.

use chrono::{DateTime, Utc};
use serde::Deserialize;
use uuid::Uuid;

use devicehub_common::{LineSensors, Motion, MotionState, Power, TelemetryV1, SCHEMA_VERSION};

/// One line of serial output from `firmware/telemetry`.
///
/// ```json
/// {"v":1,"seq":7,"ms":1400,"dist_cm":23.4,"line":{"l":120,"c":860,"r":130}}
/// ```
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct SerialFrame {
    pub v: u16,
    pub seq: u32,
    #[serde(default)]
    pub ms: Option<u32>,
    #[serde(default)]
    pub dist_cm: Option<f64>,
    #[serde(default)]
    pub line: Option<LineSensors>,
    #[serde(default)]
    pub batt_mv: Option<i32>,
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum FrameError {
    #[error("not json: {0}")]
    Json(String),
    #[error("unsupported schema version {0}")]
    Version(u16),
}

/// Identity fields that stay constant for a serial session.
#[derive(Debug, Clone)]
pub struct Envelope {
    pub device_id: Uuid,
    /// One per serial session: a reset or replug produces a new value, which
    /// is what the ingest worker uses to separate sequence spaces.
    pub boot_id: Uuid,
    pub fw_version: String,
}

impl SerialFrame {
    /// Parse one serial line, tolerating a trailing `\r`.
    pub fn parse(line: &str) -> Result<Self, FrameError> {
        let frame: SerialFrame = serde_json::from_str(line.trim_end_matches('\r'))
            .map_err(|e| FrameError::Json(e.to_string()))?;
        if frame.v != SCHEMA_VERSION {
            return Err(FrameError::Version(frame.v));
        }
        Ok(frame)
    }

    /// Stamp the frame with identity and time to form the contract payload.
    pub fn into_telemetry(self, envelope: &Envelope, now: DateTime<Utc>) -> TelemetryV1 {
        TelemetryV1 {
            schema_version: SCHEMA_VERSION,
            device_id: envelope.device_id,
            boot_id: envelope.boot_id,
            seq: self.seq,
            ts: now,
            ts_mono_ms: self.ms,
            fw_version: Some(envelope.fw_version.clone()),
            distance_cm: self.dist_cm,
            line: self.line,
            // Phase 2 has no motor control, so "idle" is the honest state.
            motion: Some(Motion {
                state: MotionState::Idle,
                left_pwm: None,
                right_pwm: None,
            }),
            power: self.batt_mv.map(|battery_mv| Power {
                battery_mv: Some(battery_mv),
            }),
            config_version: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn envelope() -> Envelope {
        Envelope {
            device_id: Uuid::parse_str("0192f3c4-1a2b-7c3d-8e4f-5a6b7c8d9e0f").unwrap(),
            boot_id: Uuid::parse_str("0192f3c4-0000-7000-8000-000000000001").unwrap(),
            fw_version: "0.1.0".into(),
        }
    }

    const LINE: &str =
        r#"{"v":1,"seq":7,"ms":1400,"dist_cm":23.4,"line":{"l":120,"c":860,"r":130}}"#;

    #[test]
    fn parses_a_telemetry_line() {
        let frame = SerialFrame::parse(LINE).expect("valid frame");
        assert_eq!(frame.seq, 7);
        assert_eq!(frame.dist_cm, Some(23.4));
        assert_eq!(frame.ms, Some(1400));
    }

    #[test]
    fn tolerates_crlf() {
        let frame = SerialFrame::parse(&format!("{LINE}\r")).expect("valid frame");
        assert_eq!(frame.seq, 7);
    }

    #[test]
    fn accepts_a_two_sensor_line() {
        let two = r#"{"v":1,"seq":8,"ms":1600,"dist_cm":null,"line":{"l":120,"r":130}}"#;
        let frame = SerialFrame::parse(two).expect("valid frame");
        assert_eq!(frame.line.expect("line").c, None);
    }

    #[test]
    fn accepts_a_null_distance() {
        let no_echo = r#"{"v":1,"seq":9,"ms":1800,"dist_cm":null,"line":{"l":1,"c":2,"r":3}}"#;
        assert_eq!(SerialFrame::parse(no_echo).expect("valid").dist_cm, None);
    }

    #[test]
    fn rejects_other_versions() {
        let v2 = LINE.replace(r#""v":1"#, r#""v":2"#);
        assert_eq!(SerialFrame::parse(&v2).unwrap_err(), FrameError::Version(2));
    }

    #[test]
    fn rejects_non_json() {
        assert!(matches!(
            SerialFrame::parse("A0= 962 out=1").unwrap_err(),
            FrameError::Json(_)
        ));
    }

    #[test]
    fn enriches_the_envelope() {
        let frame = SerialFrame::parse(LINE).expect("valid");
        let now = Utc::now();
        let t = frame.into_telemetry(&envelope(), now);

        assert_eq!(t.schema_version, SCHEMA_VERSION);
        assert_eq!(t.device_id, envelope().device_id);
        assert_eq!(t.boot_id, envelope().boot_id);
        assert_eq!(t.seq, 7);
        assert_eq!(t.ts, now);
        assert_eq!(t.fw_version.as_deref(), Some("0.1.0"));
        assert_eq!(t.motion.map(|m| m.state), Some(MotionState::Idle));
        assert!(t.power.is_none());
    }

    #[test]
    fn maps_battery_voltage() {
        let with_batt = r#"{"v":1,"seq":1,"ms":0,"batt_mv":7400}"#;
        let t = SerialFrame::parse(with_batt)
            .expect("valid")
            .into_telemetry(&envelope(), Utc::now());
        assert_eq!(t.power.and_then(|p| p.battery_mv), Some(7400));
    }

    #[test]
    fn output_round_trips_as_contract_json() {
        let t = SerialFrame::parse(LINE)
            .expect("valid")
            .into_telemetry(&envelope(), Utc::now());
        let json = serde_json::to_string(&t).expect("serialise");
        let parsed: TelemetryV1 = serde_json::from_str(&json).expect("deserialise");
        assert_eq!(parsed, t);
    }
}
