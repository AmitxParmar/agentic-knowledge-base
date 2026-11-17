//! Process configuration.
//!
//! Values come from the environment. `from_map` exists so tests can build a
//! `Settings` without mutating process-global state.

use std::net::SocketAddr;

use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ConfigError {
    #[error("{0} must be set")]
    Missing(&'static str),
    #[error("{name} is invalid: {value:?}")]
    Invalid { name: &'static str, value: String },
}

/// Runtime settings shared by the API and the ingest worker.
#[derive(Clone, Debug)]
pub struct Settings {
    /// DeviceHub database. Deliberately *not* `DATABASE_URL`, which the
    /// Knowledge Base API already owns in its own service.
    pub database_url: String,
    /// Bearer token for `/v1/*`. Demo-only; see `SECURITY.md` for the real design.
    pub api_token: String,
    pub bind: SocketAddr,
    pub cors_origins: Vec<String>,
    pub db_max_connections: u32,
    pub mqtt_host: String,
    pub mqtt_port: u16,
    pub mqtt_client_id: String,
    pub mqtt_username: Option<String>,
    pub mqtt_password: Option<String>,
    /// Cloud brokers offer TLS only (usually 8883). Local Mosquitto uses plain TCP.
    pub mqtt_tls: bool,
    /// Contract prefix, `dh/v1`. Topics are `{prefix}/d/{id}/{kind}`.
    pub mqtt_topic_prefix: String,
    /// A device is offline when nothing has been seen for this long.
    pub heartbeat_timeout_secs: i64,
    /// Telemetry history retention. Neon's free tier cannot hold much more.
    pub telemetry_retention_hours: i32,
}

impl Settings {
    /// Read settings from the process environment, loading `.env` if present.
    pub fn from_env() -> Result<Self, ConfigError> {
        // A missing .env is normal in production; ignore the error.
        let _ = dotenvy::dotenv();
        Self::from_map(|key| std::env::var(key).ok())
    }

    /// Build settings from any key/value source.
    pub fn from_map<F>(get: F) -> Result<Self, ConfigError>
    where
        F: Fn(&str) -> Option<String>,
    {
        let database_url = required(&get, "HUB_DATABASE_URL")?;
        let api_token = required(&get, "HUB_API_TOKEN")?;

        let port: u16 = parse_or(&get, "PORT", 8080)?;
        let host = optional(&get, "HUB_BIND_HOST").unwrap_or_else(|| "0.0.0.0".to_string());
        let bind = format!("{host}:{port}")
            .parse::<SocketAddr>()
            .map_err(|_| ConfigError::Invalid {
                name: "HUB_BIND_HOST",
                value: host,
            })?;

        let cors_origins = optional(&get, "CORS_ORIGINS")
            .map(|raw| {
                raw.split(',')
                    .map(str::trim)
                    .filter(|origin| !origin.is_empty())
                    .map(str::to_string)
                    .collect::<Vec<_>>()
            })
            .filter(|origins| !origins.is_empty())
            .unwrap_or_else(|| vec!["http://localhost:3000".to_string()]);

        Ok(Self {
            database_url,
            api_token,
            bind,
            cors_origins,
            db_max_connections: parse_or(&get, "DB_MAX_CONNECTIONS", 5)?,
            mqtt_host: optional(&get, "MQTT_HOST").unwrap_or_else(|| "localhost".to_string()),
            mqtt_port: parse_or(&get, "MQTT_PORT", 1883)?,
            mqtt_client_id: optional(&get, "MQTT_CLIENT_ID").unwrap_or_else(|| {
                format!("hub-worker-{}", &uuid::Uuid::new_v4().to_string()[..8])
            }),
            mqtt_username: optional(&get, "MQTT_USERNAME"),
            mqtt_password: optional(&get, "MQTT_PASSWORD"),
            mqtt_tls: parse_or(&get, "MQTT_TLS", false)?,
            mqtt_topic_prefix: optional(&get, "MQTT_TOPIC_PREFIX")
                .unwrap_or_else(|| "dh/v1".to_string())
                .trim_end_matches('/')
                .to_string(),
            heartbeat_timeout_secs: parse_or(&get, "HEARTBEAT_TIMEOUT_SECS", 15)?,
            telemetry_retention_hours: parse_or(&get, "TELEMETRY_RETENTION_HOURS", 48)?,
        })
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

    fn settings(pairs: &[(&str, &str)]) -> Result<Settings, ConfigError> {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect();
        Settings::from_map(|key| map.get(key).cloned())
    }

    #[test]
    fn applies_defaults() {
        let s = settings(&[
            ("HUB_DATABASE_URL", "postgres://localhost/dh"),
            ("HUB_API_TOKEN", "token"),
        ])
        .expect("valid settings");

        assert_eq!(s.bind.to_string(), "0.0.0.0:8080");
        assert_eq!(s.mqtt_port, 1883);
        assert!(!s.mqtt_tls);
        assert_eq!(s.db_max_connections, 5);
        assert_eq!(s.heartbeat_timeout_secs, 15);
        assert_eq!(s.telemetry_retention_hours, 48);
        assert_eq!(s.cors_origins, vec!["http://localhost:3000"]);
    }

    #[test]
    fn requires_database_and_token() {
        assert_eq!(
            settings(&[("HUB_API_TOKEN", "t")]).unwrap_err(),
            ConfigError::Missing("HUB_DATABASE_URL")
        );
        assert_eq!(
            settings(&[("HUB_DATABASE_URL", "postgres://x")]).unwrap_err(),
            ConfigError::Missing("HUB_API_TOKEN")
        );
    }

    #[test]
    fn reads_mqtt_tls_flag() {
        let s = settings(&[
            ("HUB_DATABASE_URL", "postgres://localhost/dh"),
            ("HUB_API_TOKEN", "token"),
            ("MQTT_TLS", "true"),
            ("MQTT_PORT", "8883"),
        ])
        .expect("valid settings");

        assert!(s.mqtt_tls);
        assert_eq!(s.mqtt_port, 8883);
    }

    #[test]
    fn splits_cors_origins() {
        let s = settings(&[
            ("HUB_DATABASE_URL", "postgres://localhost/dh"),
            ("HUB_API_TOKEN", "token"),
            ("CORS_ORIGINS", "https://a.example , ,https://b.example"),
        ])
        .expect("valid settings");

        assert_eq!(
            s.cors_origins,
            vec!["https://a.example", "https://b.example"]
        );
    }

    #[test]
    fn rejects_bad_port() {
        let err = settings(&[
            ("HUB_DATABASE_URL", "postgres://localhost/dh"),
            ("HUB_API_TOKEN", "token"),
            ("PORT", "eighty"),
        ])
        .unwrap_err();
        assert_eq!(
            err,
            ConfigError::Invalid {
                name: "PORT",
                value: "eighty".into()
            }
        );
    }
}
