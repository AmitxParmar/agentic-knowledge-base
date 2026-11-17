// Bench smoke test for the DeviceHub serial link.
//
// This is NOT the Phase 2 telemetry firmware. It exists to prove, in one
// upload, that the board flashes, the USB serial port works, and the host can
// read newline-delimited JSON at 115200.
//
// Compile/upload:
//   arduino-cli compile --fqbn arduino:avr:uno firmware/smoke
//   arduino-cli upload  -p /dev/ttyACM0 --fqbn arduino:avr:uno firmware/smoke
//
// Read it back (arduino-cli monitor can print nothing in a non-TTY shell):
//   stty -F /dev/ttyACM0 115200 raw -echo && timeout 5 cat /dev/ttyACM0

unsigned long seq = 0;

void setup() {
  Serial.begin(115200);
  // Uno R3 resets when the port opens; give the host a moment.
  while (!Serial && millis() < 3000) {
  }
  Serial.println(F("{\"boot\":\"smoke\",\"baud\":115200}"));
}

void loop() {
  seq++;
  Serial.print(F("{\"seq\":"));
  Serial.print(seq);
  Serial.print(F(",\"ms\":"));
  Serial.print(millis());
  Serial.println(F("}"));
  delay(1000);
}
