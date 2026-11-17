# Firmware

| Directory | Purpose |
|---|---|
| `smoke/` | Bench self-test: proves flash + USB serial + JSON framing at 115200 |
| `telemetry/` | Phase 2 firmware: HC-SR04 + three line sensors, newline JSON, no motors |

Board currently attached: **Arduino Uno R3** (`arduino:avr:uno`).

## Wiring — `telemetry/`

Nothing else should be connected. Motors and the motor driver stay unplugged
in Phase 2.

| Module | Module pin | Uno pin | Notes |
|---|---|---|---|
| HC-SR04 | VCC | **5V** | Uno is 5 V logic, so ECHO connects directly |
| HC-SR04 | GND | **GND** | Common ground |
| HC-SR04 | TRIG | **D7** | |
| HC-SR04 | ECHO | **D8** | |
| Line sensor, left | VCC | **5V** | |
| Line sensor, left | GND | **GND** | |
| Line sensor, left | OUT or AO | **A0** | AO if the module has both |
| Line sensor, centre | VCC | **5V** | |
| Line sensor, centre | GND | **GND** | |
| Line sensor, centre | OUT or AO | **A1** | |
| Line sensor, right | VCC | **5V** | |
| Line sensor, right | GND | **GND** | |
| Line sensor, right | OUT or AO | **A2** | |
| Battery divider (optional) | — | **A3** | Leave unwired; `ENABLE_BATTERY` is 0 |

Do not use:

- **D0 / D1** — hardware serial, shared with USB.
- **D2 / D3** — reserved for interrupts later (encoders, kill switch).
- **D3, D5, D6, D9, D10, D11** — PWM, reserved for the motor driver.
- **VIN** — do not connect a supply here while USB is plugged in.

Power: USB alone is enough for three IR modules and an HC-SR04 (well under
100 mA). Never power motors from the Uno's 5 V pin.

### Analog or digital line sensors?

`analogRead` is used either way:

- 4-pin module (`VCC, GND, DO, AO`): wire **AO**, get a 0–1023 value you can
  threshold in software.
- 3-pin module (`VCC, GND, OUT`): wire **OUT**, get roughly `0` or `1023`.

The wire contract does not change; only the usable range does.

## Flash and read

```bash
arduino-cli compile --fqbn arduino:avr:uno firmware/telemetry
arduino-cli upload  -p /dev/ttyACM0 --fqbn arduino:avr:uno firmware/telemetry

stty -F /dev/ttyACM0 115200 raw -echo
timeout 5 cat /dev/ttyACM0
```

Expected with sensors wired:

```json
{"v":1,"seq":1,"ms":200,"dist_cm":23.4,"line":[120,860,130]}
```

With nothing connected, `dist_cm` is `null` and the line values float. That is
expected, not a fault.

`arduino-cli monitor` can print nothing when stdout is not a TTY; the
`stty` + `cat` form above always works.
