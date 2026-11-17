// Pin map for the Phase 2 telemetry sketch.
//
// RECOMMENDED, NOT YET CONFIRMED. Match these against the physical wiring
// before flashing. All pins are free on an Uno R3 and deliberately avoid:
//   D0/D1  — hardware serial, used by USB
//   D2/D3  — left free for interrupts (encoders, kill switch)
//   D3,5,6,9,10,11 — PWM, reserved for the motor driver in a later phase

#pragma once

// HC-SR04 ultrasonic. 5 V module; the Uno is 5 V logic so ECHO can connect
// directly. Never connect ECHO to a 3.3 V board without a divider.
#define PIN_TRIG 7
#define PIN_ECHO 8

// Three line sensors. Use the analog-capable pins for either module type:
//   * 4-pin module (VCC, GND, DO, AO) -> wire AO here, get 0..1023
//   * 3-pin module (VCC, GND, OUT)    -> wire OUT here, get ~0 or ~1023
// The firmware reads them with analogRead, which works for both.
//
// This bench device has TWO sensors (confirmed 2026-11-17), so there is no
// centre channel. `line.c` is therefore omitted from the payload instead of
// being invented.
#define PIN_LINE_L A0
#define PIN_LINE_R A2

// Optional battery divider. Leave disabled until a divider is actually wired:
// an Uno ADC pin must never see more than 5 V.
#define ENABLE_BATTERY 0
#define PIN_BATTERY A3
// Calibrate this against a multimeter; it is not a fixed constant.
#define BATTERY_MV_PER_COUNT 10

#define SERIAL_BAUD 115200
#define SAMPLE_PERIOD_MS 200  // 5 Hz
#define ECHO_TIMEOUT_US 30000UL  // ~5 m at 58 us/cm
