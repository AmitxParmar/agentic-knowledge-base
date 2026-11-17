//! Bridge configuration.
//!
//! The bridge is a device, not a service: it needs a device identity and
//! MQTT credentials, but no database and no API token. It therefore does not
//! reuse `devicehub_common::Settings`, which requires both.

use uuid::Uuid;

use devicehub_common::ConfigError;

/// Runtime settings for `devicehub-bridge`.
#[derive(Clone, Debug)]
pub struct BridgeSettings {
    /// Serial device carrying the Arduino's newline-delimited JSON.
    pub serial_port: String,
    pub baud: u32,
    /// Identity the payload and topic are stamped with.
    pub device_id: Uuid,
    pub fw_version: String,
    pub mqtt_host: String,
    pub mqtt_port: u16,
    pub mqtt_client_id: String,
    /// Defaults to `d_<device_id>`, matching the ACL in `deploy/mosquitto/acl`.
    pub mqtt_username: Option<String>,
    pub mqtt_password: Option<String>,
    /// Contract prefix, `dh/v1`. Topics are `{prefix}/d/{id}/telemetry`.
    pub topic_prefix: String,
    /// Events held while the broker is unreachable.
    pub buffer_capacity: usize,
}

impl BridgeSettings {
    pub fn from_env() -> Result<Self, ConfigError> {
        let _ = dotenvy::dotenv();
        Self::from_map(|key| std::env::var(key).ok())
    }

    pub fn from_map<F>(get: F) -> Result<Self, ConfigError>
    where
        F: Fn(&str) -> Option<String>,
    {
        let device_id = required(&get, "HUB_DEVICE_ID")?
            .parse::<Uuid>()
            .map_err(|_| ConfigError::Invalid {
                name: "HUB_DEVICE_ID",
                value: "not a uuid".to_string(),
            })?;

        Ok(Self {
            serial_port: optional(&get, "BRIDGE_SERIAL_PORT")
                .unwrap_or_else(|| "/dev/ttyACM0".to_string()),
            baud: parse_or(&get, "BRIDGE_BAUD", 115200)?,
            device_id,
            fw_version: optional(&get, "BRIDGE_FW_VERSION").unwrap_or_else(|| "0.1.0".to_string()),
            mqtt_host: optional(&get, "MQTT_HOST").unwrap_or_else(|| "localhost".to_string()),
            mqtt_port: parse_or(&get, "MQTT_PORT", 1883)?,
            mqtt_client_id: optional(&get, "MQTT_CLIENT_ID")
                .unwrap_or_else(|| format!("bridge-{}", &Uuid::new_v4().to_string()[..8])),
            mqtt_username: optional(&get, "MQTT_USERNAME")
                .or_else(|| Some(format!("d_{device_id}"))),
            mqtt_password: optional(&get, "MQTT_PASSWORD"),
            topic_prefix: optional(&get, "MQTT_TOPIC_PREFIX")
                .unwrap_or_else(|| "dh/v1".to_string())
                .trim_end_matches('/')
                .to_string(),
            buffer_capacity: parse_or(&get, "BRIDGE_BUFFER_CAPACITY", 1000)?,
        })
    }

    /// `dh/v1/d/{device_id}/telemetry`
    pub fn telemetry_topic(&self) -> String {
        format!("{}/d/{}/telemetry", self.topic_prefix, self.device_id)
    }
}

fn required<F>(get: &F, key: &'static str) -> Result<String, ConfigError>
where
    F: Fn(&str) -> Option<String>,
{
    optional(get, key).ok_or(ConfigError::Missing(key))
}

fn optional<F>(get: &F, key: &str) -> Option<String>
where
    F: Fn(&str) -> Option<String>,
{
    get(key)
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn parse_or<F, T>(get: &F, key: &'static str, default: T) -> Result<T, ConfigError>
where
    F: Fn(&str) -> Option<String>,
    T: std::str::FromStr,
{
    match optional(get, key) {
        None => Ok(default),
        Some(raw) => raw.parse::<T>().map_err(|_| ConfigError::Invalid {
            name: key,
            value: raw,
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    const DEVICE: &str = "0192f3c4-1a2b-7c3d-8e4f-5a6b7c8d9e0f";

    fn settings(pairs: &[(&str, &str)]) -> Result<BridgeSettings, ConfigError> {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect();
        BridgeSettings::from_map(|key| map.get(key).cloned())
    }

    #[test]
    fn applies_defaults() {
        let s = settings(&[("HUB_DEVICE_ID", DEVICE)]).expect("valid");
        assert_eq!(s.serial_port, "/dev/ttyACM0");
        assert_eq!(s.baud, 115200);
        assert_eq!(s.mqtt_port, 1883);
        assert_eq!(s.buffer_capacity, 1000);
        assert_eq!(s.topic_prefix, "dh/v1");
        assert_eq!(
            s.telemetry_topic(),
            "dh/v1/d/0192f3c4-1a2b-7c3d-8e4f-5a6b7c8d9e0f/telemetry"
        );
    }

    #[test]
    fn defaults_username_to_the_device_user() {
        let s = settings(&[("HUB_DEVICE_ID", DEVICE)]).expect("valid");
        assert_eq!(
            s.mqtt_username.as_deref(),
            Some("d_0192f3c4-1a2b-7c3d-8e4f-5a6b7c8d9e0f")
        );
    }

    #[test]
    fn requires_device_id() {
        assert_eq!(
            settings(&[]).unwrap_err(),
            ConfigError::Missing("HUB_DEVICE_ID")
        );
    }

    #[test]
    fn rejects_bad_device_id() {
        assert!(matches!(
            settings(&[("HUB_DEVICE_ID", "robot-1")]).unwrap_err(),
            ConfigError::Invalid {
                name: "HUB_DEVICE_ID",
                ..
            }
        ));
    }

    #[test]
    fn strips_trailing_slash_from_prefix() {
        let s =
            settings(&[("HUB_DEVICE_ID", DEVICE), ("MQTT_TOPIC_PREFIX", "dh/v1/")]).expect("valid");
        assert_eq!(s.topic_prefix, "dh/v1");
    }
}
