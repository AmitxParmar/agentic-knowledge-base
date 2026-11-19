//! DeviceHub hub: MQTT ingest, read API, and SSE.
//!
//! The API and the worker are separate modules with separate responsibilities.
//! They may run in one process (`bin/all.rs`) or separately, per ADR-0014.

#![deny(unsafe_code)]

pub mod api;
pub mod db;
pub mod state;
pub mod telemetry;
pub mod worker;
