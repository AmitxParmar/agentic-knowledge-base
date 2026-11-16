//! Shared configuration and wire contracts for the DeviceHub device plane.
//!
//! Everything here is transport- and storage-agnostic so the hub, the future
//! bridge, and the tests can agree on one definition of a valid message.

#![deny(unsafe_code)]

pub mod config;
pub mod wire;

pub use config::{ConfigError, Settings};
pub use wire::{
    clamp_ts, parse_status, parse_telemetry, DeviceOnlineState, LineSensors, Motion, MotionState,
    Power, Reject, StatusV1, TelemetryV1, MAX_TELEMETRY_BYTES, SCHEMA_VERSION,
};
