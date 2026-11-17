// DeviceHub Phase 2 telemetry firmware.
//
// Reads an HC-SR04 and three line sensors and writes one JSON object per line
// at 115200 baud. No motors, no commands: Phase 2 is telemetry only.
//
// The bridge adds device_id, boot_id, ts, fw_version, and motion.state before
// publishing to MQTT, so this sketch only reports what the MCU knows.
//
// Output:
//   {"v":1,"seq":7,"ms":1400,"dist_cm":23.4,"line":[120,860,130]}
//
// A line ends with '\n' only. Arduino's println() would append '\r\n'.

#include "config.h"

static uint32_t seq = 0;
static uint32_t last_sample_ms = 0;

// Returns tenths of a centimetre, or 0 when the echo times out.
// Integer math only: float formatting costs flash and is not needed.
static uint32_t ping_tenths_cm() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  unsigned long echo_us = pulseIn(PIN_ECHO, HIGH, ECHO_TIMEOUT_US);
  if (echo_us == 0) {
    return 0;
  }
  // 58 us per cm -> tenths = us * 10 / 58
  return (uint32_t)((echo_us * 10UL + 29UL) / 58UL);
}

static void print_u32(uint32_t value) {
  Serial.print(value);
}

static void print_reading() {
  seq++;
  uint32_t distance = ping_tenths_cm();

  Serial.print(F("{\"v\":1,\"seq\":"));
  print_u32(seq);

  Serial.print(F(",\"ms\":"));
  print_u32((uint32_t)millis());

  Serial.print(F(",\"dist_cm\":"));
  if (distance == 0) {
    Serial.print(F("null"));
  } else {
    print_u32(distance / 10);
    Serial.print('.');
    print_u32(distance % 10);
  }

  Serial.print(F(",\"line\":["));
  Serial.print((int)analogRead(PIN_LINE_L));
  Serial.print(',');
  Serial.print((int)analogRead(PIN_LINE_C));
  Serial.print(',');
  Serial.print((int)analogRead(PIN_LINE_R));
  Serial.print(']');

#if ENABLE_BATTERY
  Serial.print(F(",\"batt_mv\":"));
  print_u32((uint32_t)analogRead(PIN_BATTERY) * BATTERY_MV_PER_COUNT);
#endif

  Serial.print(F("}\n"));
}

void setup() {
  Serial.begin(SERIAL_BAUD);

  pinMode(PIN_TRIG, OUTPUT);
  digitalWrite(PIN_TRIG, LOW);
  pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_LINE_L, INPUT);
  pinMode(PIN_LINE_C, INPUT);
  pinMode(PIN_LINE_R, INPUT);
#if ENABLE_BATTERY
  pinMode(PIN_BATTERY, INPUT);
#endif

  // Let the USB-serial bridge settle before the first line.
  delay(200);
}

void loop() {
  uint32_t now = (uint32_t)millis();
  if (now - last_sample_ms < SAMPLE_PERIOD_MS) {
    return;
  }
  last_sample_ms = now;
  print_reading();
}
