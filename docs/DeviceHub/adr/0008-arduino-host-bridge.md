# ADR-0008: Connect the Arduino through a host bridge
Status: Accepted (provisional, hardware TBD) · Date: 2026-11-13

## Context
The exact Arduino board and any network module are not yet identified. Many classic boards have no network stack.

## Decision
The MCU talks over USB serial (COBS framing, CRC-16) to a bridge process on a host computer. The bridge holds the device credential, connects to MQTT over TLS, signs/verifies per the contracts, allow-lists commands, and buffers telemetry during broker outages. Control logic and safety stay on the MCU.

## Alternatives considered
- WiFi/Ethernet module on the board: closer to a real IoT device, but depends on hardware not yet confirmed and adds MCU memory and security constraints.
- Bluetooth to a phone: extra platform and pairing complexity.

## Consequences
+ Works with almost any board; keeps the backend work unblocked; easy debugging.
− The host is a single point of failure and part of the trust boundary; the robot is tethered by USB unless the host rides on it.
Mitigation: comms-loss stop on MCU; the protocol is defined so a native network client can replace the bridge later.

## Revisit when
The inventory shows a network-capable board, or the host cannot travel with the robot.
