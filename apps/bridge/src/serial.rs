//! Blocking serial reader.
//!
//! `serialport` is a blocking API, so it runs on its own thread and hands
//! whole lines to the async side. 5–20 Hz does not justify an async serial
//! stack (ADR-0015).

use std::io::ErrorKind;
use std::time::Duration;

use tokio::sync::mpsc;
use tracing::{info, warn};

use crate::config::BridgeSettings;

/// What the serial link reports to the async side.
#[derive(Debug)]
pub enum LinkEvent {
    /// Port opened: a fresh session, treated as a new device boot.
    Opened,
    Line(String),
    /// Port read failed; the thread will try to reopen.
    Lost,
}

const READ_TIMEOUT: Duration = Duration::from_millis(250);
const MAX_PENDING_BYTES: usize = 4096;

pub fn spawn(settings: BridgeSettings, tx: mpsc::Sender<LinkEvent>) -> std::thread::JoinHandle<()> {
    std::thread::Builder::new()
        .name("bridge-serial".to_string())
        .spawn(move || read_forever(&settings, &tx))
        .expect("spawn serial thread")
}

fn read_forever(settings: &BridgeSettings, tx: &mpsc::Sender<LinkEvent>) {
    loop {
        match serialport::new(&settings.serial_port, settings.baud)
            .timeout(READ_TIMEOUT)
            .open()
        {
            Ok(mut port) => {
                info!(port = %settings.serial_port, baud = settings.baud, "serial port open");
                if tx.blocking_send(LinkEvent::Opened).is_err() {
                    return;
                }
                if !pump(&mut *port, tx) {
                    return;
                }
                let _ = tx.blocking_send(LinkEvent::Lost);
            }
            Err(error) => {
                warn!(%error, port = %settings.serial_port, "cannot open serial port");
            }
        }
        std::thread::sleep(Duration::from_secs(1));
    }
}

/// Read until the port fails or the receiver goes away.
/// Returns `false` when the receiver is gone.
fn pump(port: &mut dyn serialport::SerialPort, tx: &mpsc::Sender<LinkEvent>) -> bool {
    let mut buffer = [0u8; 256];
    let mut pending: Vec<u8> = Vec::new();

    loop {
        match port.read(&mut buffer) {
            Ok(0) => {}
            Ok(read) => {
                pending.extend_from_slice(&buffer[..read]);
                while let Some(newline) = pending.iter().position(|byte| *byte == b'\n') {
                    let mut line: Vec<u8> = pending.drain(..=newline).collect();
                    line.pop();
                    let Ok(text) = String::from_utf8(line) else {
                        warn!("serial line was not valid utf-8");
                        continue;
                    };
                    let text = text.trim_end_matches('\r').to_string();
                    if text.is_empty() {
                        continue;
                    }
                    if tx.blocking_send(LinkEvent::Line(text)).is_err() {
                        return false;
                    }
                }
                if pending.len() > MAX_PENDING_BYTES {
                    warn!("serial line exceeded {MAX_PENDING_BYTES} bytes; discarding");
                    pending.clear();
                }
            }
            Err(error) if error.kind() == ErrorKind::TimedOut => {}
            Err(error) => {
                warn!(%error, "serial read failed");
                return true;
            }
        }
    }
}
