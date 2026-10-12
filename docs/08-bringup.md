# 8. Bring-up and test plan

## 8.1 Equipment

| Item | Have | Use / notes |
|---|---|---|
| Current-limited bench supply | ✅ | Every stage starts current-limited. Note its maximum voltage: stages 8+ need 48–52 V |
| Oscilloscope | ✅ | Gate (low side), switch nodes, CSA outputs, V_BUS ripple. Use the ground spring, not the long lead, on switch nodes |
| BLDC test motors | ✅ | One gimbal motor (high R, easy first spin) and one 5010-class with a magnet holder |
| Electronic load / dyno | ✅ | Two jobs: load motor or brake for thermal runs, **and** regen clamp (8.2) |
| B-G431B-ESC1 | buy (~$20) | Firmware platform before rev A exists ([07](07-firmware.md) §7.8) |
| MT6835 breakout + diametric magnets | buy (~$10–20) | For the ESC1 and for checking magnet gaps |
| Thermocouple or thermal camera | recommended | Thermocouples (K-type, Kapton tape) on two FET cases and the board centre are enough for the rating. A thermal camera speeds up finding hot spots |
| Differential or isolated probe | optional | Only for high-side gate waveforms. Low-side measurements are ground-referenced and enough for rev A |
| Current probe / clamp | optional | Otherwise use the CSA outputs plus a known series shunt on one phase for cross-checks |
| Inline fuse (10–15 A) + XT30 pigtails, anti-spark XT90-S on any battery | buy | Battery tests and hot-plug |
| ST-Link (V2/V3) + Tag-Connect TC2030-NL cable | check | SWD through pads. The cable is ~$40, or use pogo pins on a printed jig |
| A small LiFePO4/LiPo pack (6S–12S) | optional | The easiest regen-tolerant source for stages 10–11 |

## 8.2 Regen and overvoltage on the bench

A bench supply **cannot sink current**. Braking a motor pumps V_BUS up, and at
52 V nominal there is little headroom before the 80 V FETs. Three layers:

1. **Firmware:** `MaxRegenCurrent` (start at 0.5 A) and the
   overvoltage-aware braking clamp ([07](07-firmware.md) §7.6). Tested in
   the simulator first (test 7).
2. **Bench clamp:** put the electronic load in **CV mode** across the bus,
   set ~3 V above the supply voltage. Add a series diode (or the supply's own
   protection) so the load, not the supply, absorbs the pump-up. Add a
   1000 µF+ 63/100 V electrolytic on the bench side of the XT30 to damp cable
   ringing.
3. **Battery:** for aggressive braking tests, run from a battery (it absorbs
   regen), with an inline fuse.

Hot-plug at 48 V with an MLCC-heavy board can ring to ~2× V_BUS. Measure it
once at each voltage step (stage 8) with the scope on V_BUS at the XT30, and
use a precharge or anti-spark connector from then on.

## 8.3 Staged power-up

Each stage has a pass criterion and is logged in a bring-up notes file per
board serial. Stop at the first failure; never "just try" the next stage.

| Stage | Setup | Do | Pass |
|---|---|---|---|
| 0. Visual + passive | Unpowered | Inspect solder (QFN, FETs, XT30). Resistance V_BUS–GND, 5 V–GND, 3V3–GND, each phase to V_BUS and GND | No shorts; values match a known-good reference board after the first |
| 1. Logic rails | 12 V, 50 mA limit, no motor | Power up. Driver ENABLE stays low (pull-down, MCU blank) | 5 V and 3.3 V within 2 %; idle current as expected (~30–60 mA) |
| 2. MCU + peripherals | 12 V, 100 mA | Flash the bring-up firmware over SWD: LEDs, HSE check (`kInfoCrystalClock`), CAN `GetInfo` from the FD at 500k/2.5M **and** 1M/5M, MT6835 angle (turn a magnet by hand), V_BUS and NTC readings, DRV8353 register read/write | All read back correctly; CAN error counters at 0 |
| 3. Gate drive, no motor | 12 V, 100 mA | One leg at a time, then all three: 50 % PWM at 20 kHz. Scope low-side gate, switch node, dead time | Clean edges, dead time as set, no supply-current spike (no shoot-through), no DRV faults |
| 4. Current sense zero | 12 V, no motor | CSA offset calibration; check each gain setting | Offsets within spec, noise ≤ a few LSB |
| 5. First spin, open loop | 12 V, 1 A limit, gimbal motor | Rotating voltage vector at low amplitude | Smooth rotation; three phase currents sum ≈ 0; current signs match the model |
| 6. Calibration + current loop | 12 V, 2 A | Offsets, R, L, pole pairs, direction, encoder offset and linearity. Then i_q steps | Identified values match a multimeter/LCR within ~10 %; step response matches the sim |
| 7. Outer loops + protocol | 12–24 V | Velocity, position, trajectory, torque and impedance via Python and Tercio Control; mixed bus with an S1 | Settling and tracking as in sim; S1 + B1 move from one script |
| 8. Voltage steps | 24 → 36 → 48 → 52 V, limit raised gradually | At each step: switch-node ringing, V_BUS hot-plug transient, DRV faults, temperatures | V_DS peak < 64 V (80 % of 80 V) at 52 V; no faults |
| 9. Thermal (continuous rating) | 24–48 V, dyno or locked rotor | 5 / 10 / 15 A RMS until steady state (≥ 20 min each), thermocouples on FETs and board | Defines the published continuous rating (method in [01](01-requirements.md) §1.5) |
| 10. Peak current | Locked rotor, q-axis current | 40 → 60 → 80 A pulses of 0.2 → 1 s. Locked-rotor tests draw only I²R from the supply, so a bench supply can do them | No DRV faults, FET temperature rise per pulse logged; sets the peak rating and duration |
| 11. Regen | Inertia wheel on the dyno, e-load CV clamp, then battery | Hard decelerations; supply-side disconnect while braking | V_BUS stays under the OV limit, or the OV fault trips cleanly; no damage |
| 12. Fault injection | 24 V | Lower VDS_LVL until OCP trips on a load step; pull the magnet off; unplug CAN (deadman); force over-temperature thresholds low; corrupt encoder CRC | Each fault reaches the right state and telemetry bit within its budget ([07](07-firmware.md) §7.6) |
| 13. Bus robustness | 48 V, full current | Run at 5 Mbit/s with an S1 and the FD on a 1–2 m GH daisy chain while the B1 runs at full current | CAN error counters stay at 0; no stuff/form errors |
| 14. Soak | 24–48 V | 24 h trajectory loop at moderate load | No resets, no drift in the zero, no faults |

## 8.4 Firmware for bring-up

- `bringup` PlatformIO environment: the same drivers as the product
  firmware, plus a serial-over-CAN text console (a small command set:
  `drv read`, `pwm leg a 50`, `adc`, `enc`, `can`). No FOC until stage 5.
- Every stage that moves current has a hard current limit in firmware **and**
  on the supply.
- The first power-stage test always runs at 12 V with the 50–100 mA supply
  limit. A shoot-through then shows up as the supply going into
  current-limit, not as smoke.

## 8.5 Production test (for rev C)

Pogo-pin fixture on the Tag-Connect and test points:

1. Flash bootloader and application.
2. Rail and current checks.
3. CSA offset and gain against a fixture load (a known resistor on each
   phase).
4. Encoder against a fixture magnet.
5. CAN loopback through the FD.
6. Short spin on a reference motor.

Results are logged against the MCU UID, which is already in `GetInfo`.
