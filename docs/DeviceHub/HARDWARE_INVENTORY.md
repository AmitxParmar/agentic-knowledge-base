# HARDWARE INVENTORY

Physical component inventory for the DeviceHub demo robot. **No component has been inspected yet.** Everything below is `unknown` until you record it; nothing here is inferred from a product name, a photo you have not sent, or a typical build.

Hardware facts are the input to Phase 2 (first vertical slice) and Phase 4 (robot integration). They are not required to finish Phase 1.

## 1. Status vocabulary

**Owner-reported (2026-11-16):** Arduino Nano works; IR line sensors, ultrasonic sensor, and a motor controller are on hand, condition unknown. Nothing below has been verified on the bench yet.

| Status | Meaning |
|---|---|
| `unknown` | Not identified. No assumption may be made. |
| `not inspected` | Present (maybe) but not physically examined. |
| `needs testing` | Identified, but function is unverified. |
| `working` | Verified on the bench, with the test recorded. |
| `not working` | Verified failure, with the symptom recorded. |
| `missing` | Needed but not owned. |

## 2. Inventory

| # | Component | Required detail | Status | Notes / source |
|---|---|---|---|---|
| H1 | Arduino board | Manufacturer, exact model, silkscreen marking, logic voltage | `working` — **Uno R3** detected | USB `2341:0043` ("Arduino SA Uno R3, CDC ACM") on `/dev/ttyACM0`, `arduino:avr:uno`, core `1.8.8`. Owner originally reported a **Nano**; confirm which board is the bench target. Both are ATmega328P / 5 V, so the firmware design is unchanged apart from pin count and form factor. |
| H2 | Motor driver / controller | Model, channel count, max current, logic vs motor supply | `not inspected` | Owner reports present; model unconfirmed. Not needed for the Phase 2 telemetry slice. |
| H3 | Ultrasonic distance sensor | Model, trigger/echo or I2C, supply voltage, measured range | `verified` — reads 39–41 cm | HC-SR04-class, 4 pins, D7 (TRIG) / D8 (ECHO) / 5V / GND. A second module reads a stable 39–41 cm at bench distance with no `null` samples. The first module never produced an echo while its ECHO pin was confirmed powered, so it is treated as faulty. Pin order is normal: with TRIG/ECHO swapped in software the ECHO line reads unpowered, which only happens if D8 really is the module's ECHO. |
| H4 | Line-following sensors | Technology (IR reflectance vs analog), count, spacing | `verified` — **3 sensors** | Three 3-pin IR modules wired to A0/A1/A2 and bench-tested on 2026-11-17. All respond; they output an analog level, not a bare comparator. Measured span: A0 39–973, A1 78–976, A2 443–747. A2 is compressed and needs its own threshold. Spacing unmeasured. |
| H5 | Drive motors | Count, type (DC/stepper/servo), rated voltage and current, gearbox | `unknown` | Two independently driven wheels are assumed by `motion.left_pwm/right_pwm`. |
| H6 | Chassis / wheels | Availability, wheel diameter, caster/tracks | `unknown` | Affects speed limits only, not contracts. |
| H7 | Power supply / battery | Chemistry, nominal voltage, capacity, discharge current, connector, fuse | `unknown` | Motor and logic rails must be separated or decoupled; unknown until measured. |
| H8 | USB cable and serial path | Cable type, USB-serial chip, does the board enumerate, port name | `unknown` | ADR-0008 depends on a working USB serial link. |
| H9 | Network module | Wi-Fi / Ethernet / Bluetooth present? Model? | `unknown` | If present, ADR-0008 should be revisited; the bridge stays provisional either way. |
| H10 | Physical e-stop / kill switch | Present? Wired to motor power or MCU? | `unknown` | Required by `SECURITY` §7 before any floor test. |
| H11 | Spare parts / replacement stock | What exists beyond the assembled robot | `unknown` | Do not buy anything based on assumptions. |
| H12 | Datasheets / manuals | Link or local file per component | `unknown` | Needed for RAG over manuals (`FR-22`) and for correct wiring. |

## 3. Information to capture per component

For each row above, record only observed facts:

1. Photograph the silkscreen or label; transcribe the exact model string.
2. Note the supply voltage and current the component expects, from its datasheet — not from memory.
3. Note pin labels exactly as printed.
4. Note physical condition: corrosion, missing pins, damaged connectors, prior soldering.
5. Note the test performed and its observed result.

Do not record a wiring plan until H1–H7 are identified. Do not record voltage or current ratings that were not read from a datasheet or a meter.

## 4. Bench tests still required

These are Phase 4 gates, not Phase 1 work. Enumerating and uploading were performed on the **Uno R3** on 2026-11-17; the rest are untested.

| Test | Pass condition | Status |
|---|---|---|
| Board enumerates over USB | Host sees a stable serial device across replug | `pass` — Uno R3 on `/dev/ttyACM0` (USB `2341:0043`, `cdc_acm`), `arduino-cli board list` resolves `arduino:avr:uno` |
| Upload a trivial sketch | Sketch runs; serial output observed | `pass` — 2026-11-17, `firmware/smoke` prints `{"seq":n,"ms":…}` every second at 115200; captured with a raw read |
| Ultrasonic returns plausible distances | Readings track a moving hand between known distances | `not tested` |
| Each line sensor responds to contrast | Per-channel values change on tape vs floor | `not tested` |
| Motor driver moves one wheel (wheels lifted) | Direction and PWM response correct at low duty | `not tested` |
| Motor driver moves both wheels (wheels lifted) | Independent control, no brownout | `not tested` |
| Battery sustains motors and logic | No reset under stall-free load; voltage logged | `not tested` |
| Physical kill switch cuts motor power | Motors stop immediately, logic may stay alive | `not tested` |
| Comms-loss stop | MCU stops within the configured timeout when the link is cut | `not tested` |
| Obstacle stop | MCU stops before contact at the configured threshold | `not tested` |
| E-stop latch | `estop` stops and stays stopped until `reset_estop` | `not tested` |

Protocol for every motor test: **wheels lifted or motors disconnected, motor power switch off until the moment of the test, kill switch within reach.** Record the result, not the intention.

## 5. Safety assumptions that do not depend on the inventory

These hold regardless of which components are confirmed, and are already fixed by ADR-0005 and `SECURITY` §7:

- Motor control, speed limits, obstacle thresholds, and the e-stop latch are implemented in firmware, not in the agent or the backend.
- The LLM cannot emit pin writes, raw PWM, or threshold changes; those are not representable in the command catalog.
- Loss of communication must stop the robot without depending on the network path.
- No motor test happens on the floor before the bench tests above pass.

## 6. Decisions blocked on this inventory

| Decision | Blocked until |
|---|---|
| Final pin assignment and wiring diagram | H1–H5, H7 identified |
| Serial frame layout and baud rate | H1, H8 tested |
| Telemetry rate and payload budget | H1 memory, H8 link quality measured |
| Whether the bridge is required at all | H9 (on-board networking) |
| Valid `distance_cm` range and threshold | H3 datasheet plus measured behaviour |
| Left/centre/right channel labelling | H4 measured 2026-11-17; physical mapping confirmed on the floor |
| Battery fields in telemetry (`power.battery_mv`) | H7 supports voltage sensing |
| Bench safety sign-off before any floor test | H10 present and tested, all bench tests passed |
