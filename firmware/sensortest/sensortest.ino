// Bench test for the three-pin IR modules and the HC-SR04.
//
// This is NOT the telemetry firmware. It exists to answer one question:
// does each sensor respond at all, and which physical side is A0 / A1 / A2?
//
// Printed line, four times a second:
//   IR1=1023 out=1 | IR2=  12 out=0 | IR3=1005 out=1 | dist= 23.4 cm
//
// IR1/IR2/IR3 are pins A0/A1/A2 in that order, not digital pin names.
//
// Reading it:
//   * A three-pin module has no analog output. Its OUT pin is already a
//     comparator decision, so analogRead shows roughly 0 or roughly 1023.
//     The out column is the honest one: 0 or 1.
//   * A dead channel sits at 0/false and never moves when you slide a surface
//     under it. A live channel flips when white paper replaces black tape.
//   * If a channel is live but never flips, adjust the small potentiometer on
//     the module until the LED changes state at the surface you care about.
//   * dist is null when the ultrasonic echo times out.

#define PIN_TRIG 7
#define PIN_ECHO 8
#define PIN_IR1 A0
#define PIN_IR2 A1
#define PIN_IR3 A2

#define SERIAL_BAUD 115200
#define SAMPLE_PERIOD_MS 250
#define ECHO_TIMEOUT_US 30000UL

static uint32_t last_sample_ms = 0;

// Right-align a 0..1023 value in four characters so columns stay readable.
static void print_pad4(int value) {
  if (value < 1000) {
    Serial.print(' ');
  }
  if (value < 100) {
    Serial.print(' ');
  }
  if (value < 10) {
    Serial.print(' ');
  }
  Serial.print(value);
}

static void print_channel(const __FlashStringHelper *name, uint8_t pin) {
  Serial.print(name);
  Serial.print('=');
  print_pad4((int)analogRead(pin));
  Serial.print(F(" out="));
  Serial.print((int)digitalRead(pin));
}

static void print_distance() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  unsigned long echo_us = pulseIn(PIN_ECHO, HIGH, ECHO_TIMEOUT_US);
  Serial.print(F("dist="));
  if (echo_us == 0) {
    Serial.print(F(" null"));
    return;
  }
  uint32_t tenths = (uint32_t)((echo_us * 10UL + 29UL) / 58UL);
  if (tenths < 1000) {
    Serial.print(' ');
  }
  if (tenths < 100) {
    Serial.print(' ');
  }
  if (tenths < 10) {
    Serial.print(' ');
  }
  Serial.print(tenths / 10);
  Serial.print('.');
  Serial.print(tenths % 10);
  Serial.print(F(" cm"));
}

void setup() {
  Serial.begin(SERIAL_BAUD);

  pinMode(PIN_TRIG, OUTPUT);
  digitalWrite(PIN_TRIG, LOW);
  pinMode(PIN_ECHO, INPUT);

  pinMode(PIN_IR1, INPUT);
  pinMode(PIN_IR2, INPUT);
  pinMode(PIN_IR3, INPUT);

  delay(200);
}

void loop() {
  uint32_t now = (uint32_t)millis();
  if (now - last_sample_ms < SAMPLE_PERIOD_MS) {
    return;
  }
  last_sample_ms = now;

  print_channel(F("A0"), PIN_IR1);
  Serial.print(F(" | "));
  print_channel(F("A1"), PIN_IR2);
  Serial.print(F(" | "));
  print_channel(F("A2"), PIN_IR3);
  Serial.print(F(" | "));
  print_distance();
  Serial.print('\n');
}
