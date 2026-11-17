# Firmware

| Directory | Purpose |
|---|---|
| `smoke/` | Bench self-test: proves flash + USB serial + JSON framing at 115200 |
| `telemetry/` | Phase 2 firmware: HC-SR04 + two line sensors, newline JSON, no motors |

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
| Line sensor, right | VCC | **5V** | |
| Line sensor, right | GND | **GND** | |
| Line sensor, right | OUT or AO | **A2** | |
| Battery divider (optional) | — | **A3** | Leave unwired; `ENABLE_BATTERY` is 0 |

Do not use:

- **D0 / D1** — hardware serial, shared with USB.
- **D2 / D3** — reserved for interrupts later (encoders, kill switch).
- **D3, D5, D6, D9, D10, D11** — PWM, reserved for the motor driver.
- **VIN** — do not connect a supply here while USB is plugged in.

Power: USB alone is enough for two IR modules and an HC-SR04 (well under
100 mA). Never power motors from the Uno's 5 V pin.

### Analog or digital line sensors?

This bench device has **two** sensors, so the payload omits `line.c`.

`analogRead` is used either way:

- 4-pin module (`VCC, GND, DO, AO`): wire **AO**, get a 0–1023 value you can
  threshold in software.
- 3-pin module (`VCC, GND, OUT`): wire **OUT**, get roughly `0` or `1023`.

The wire contract does not change; only the usable range does.

## Breadboard layout (mini board, 4-hole rows)

A mini breadboard's rows are horizontal nodes: **every hole in one row is the
same wire**, and the centre gap separates the left half from the right half.
That has two consequences.

1. **Never plug the 4-pin HC-SR04 along a row** — that shorts VCC, TRIG, ECHO
   and GND together. Insert modules **across** the rows so each pin lands in
   its own row.
2. Use two rows as power buses:

```
row 1      [5V][5V][5V][5V] │ [ ][ ][ ][ ]    <- 5V bus
row 2      [G ][G ][G ][G ] │ [ ][ ][ ][ ]    <- GND bus
row 3-6    HC-SR04, one pin per row: VCC, TRIG, ECHO, GND
row 7-9    IR left, one pin per row: VCC, GND, OUT -> A0
row 10-12  IR right, one pin per row: VCC, GND, OUT -> A2
```

With 4-hole rows the bus is exactly full: one lead from the Arduino plus three
module leads.

| From | To | Jumper |
|---|---|---|
| Arduino **5V** | row 1 | 1 male–male |
| Arduino **GND** | row 2 | 1 male–male |
| row 1 | HC-SR04 VCC | 1 |
| row 1 | IR left VCC | 1 |
| row 1 | IR right VCC | 1 |
| row 2 | HC-SR04 GND | 1 |
| row 2 | IR left GND | 1 |
| row 2 | IR right GND | 1 |
| HC-SR04 TRIG | Arduino **D7** | 1 |
| HC-SR04 ECHO | Arduino **D8** | 1 |
| IR left OUT/AO | Arduino **A0** | 1 |
| IR right OUT/AO | Arduino **A2** | 1 |

That is 12 jumpers. If you only have male–male leads, push the module pins
into their own rows and run male–male from those rows to the Arduino; the
Arduino's headers are female sockets, so male–male is what fits them either
way.

Order of work: **unplug USB**, wire ground first, then 5 V, then signals, check
each module's silkscreen for VCC/GND order, then power up and flash.

## Flash and read

```bash
arduino-cli compile --fqbn arduino:avr:uno firmware/telemetry
arduino-cli upload  -p /dev/ttyACM0 --fqbn arduino:avr:uno firmware/telemetry

stty -F /dev/ttyACM0 115200 raw -echo
timeout 5 cat /dev/ttyACM0
```

Expected with sensors wired:

```json
{"v":1,"seq":1,"ms":200,"dist_cm":23.4,"line":{"l":120,"r":130}}
```

With nothing connected, `dist_cm` is `null` and the line values float. That is
expected, not a fault.

`arduino-cli monitor` can print nothing when stdout is not a TTY; the
`stty` + `cat` form above always works.
