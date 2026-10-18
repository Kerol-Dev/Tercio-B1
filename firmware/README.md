# Tercio B1 firmware

Milestone **F0** of [docs/07-firmware.md](../docs/07-firmware.md) §7.10: the
hardware-independent firmware, tested on a simulated motor, plus a real-time
simulator with a web UI for trying the joint before rev A exists.

```bash
cd ~/Documents/Projects/Tercio-B1/firmware
~/.platformio/penv/bin/pio test -e native      # 7 host tests, ~15 s
node simulator/server.mjs                       # http://127.0.0.1:8770 (builds the simulator first if needed)
```

## Layout

| Path | Runs on | What |
|---|---|---|
| `src/foc/` | MCU + host | `FocCore`: one call per PWM period, ADC sample in, duties out. Clarke/Park, SVPWM, d/q current PI with predicted-current decoupling, latency compensation, phase drop at high modulation, per-tick protection. `Calibration`: offsets, R, L, pole pairs, direction, encoder offset, flux linkage |
| `src/control/` | MCU + host | S1's `Trajectory` (plus `resync`), `EncoderTracker` (32-bit raw for 21-bit counts), `Fixed`; `OuterLoop` (position/impedance, velocity, torque) |
| `src/app/Joint` | MCU + host | The application: states (protocol v2 numbering), outer loop every 2nd tick, regen clamp, deadman, NTC derating, fault policy, CSA zero tracking while the bridge is off |
| `src/sim/` | host only | `Motor`: dq PMSM + mechanics, average inverter with dead time, supply and bus capacitance, board and winding thermal models. `Bench`: CSA codes, MT6835 reads, DRV8353 VDS shutdown and UVLO, NTC codes, TIM1 pipeline timing |
| `src/simulator/` | host only | Real-time loop: `Joint` + `Bench`, JSON lines on stdin/stdout |
| `simulator/` | host only | `server.mjs` (Node, no dependencies) and the web UI in `public/` |
| `test/test_foc/` | host | Unity tests 1–6 of §7.7 (plus the Joint) |

No HAL anywhere in `foc/`, `control/` or `app/`; the MCU's `main.cpp`
(F1/F2) will feed `Joint::tick()` from the ADC interrupt and write TIM1, as
the simulator feeds it from `Bench`. These sources build for the G431
(Cortex-M4F, `-Wdouble-promotion`) with no warnings, ~15 KB of code so far.

## Tests (§7.7)

| # | Test | Result on the simulated motors |
|---|---|---|
| 1 | Clarke/Park/SVPWM reference values; SVPWM stays linear | exact; over-range vectors scaled onto V_bus/√3 |
| 2 | i_q step, locked rotor (5010) | 10–90 % in 0.10 ms, 2 % overshoot, 0.02 % error |
| 3 | Decoupling at half base speed | i_d moves 0.44 A on a 10 A step (3.9 A without) |
| 4 | Pole pairs, direction, encoder offset (gimbal, 5010, 2204; encoders mounted at unknown angles, two reversed) | exact pp and direction; offset within 0.02° electrical |
| 5 | R, L, λ within 5 %, dead time on | 5010 and 2204 within 1 %; gimbal R +3.5 % (see below) |
| 6 | Planner tracking through the Joint | 1-turn move: 0.0096 turn worst lag, 0.0016 overshoot, 0.00014 final; velocity mode 5.0001 turns/s |

Tests 7 (regen into a bench supply) and 8 (fault reaction times) are next;
the regen clamp and the fault paths exist and can be tried in the simulator.

## Simulator

The UI runs the firmware code above, unchanged, at 30 kHz against the plant,
in real time (0.1× to ~5× faster on this Mac). Left: the bench (motor, supply,
load, environment, fault injection). Middle: the motor seen from the shaft end
(true rotor angle, phase-current glow on the stator teeth; drag it to twist the
shaft by hand) and a scope (1 kHz stream, 30 s history; or a 30 kHz capture of
one PWM period at a time). Right: the joint as a CAN host would command it,
calibration with found-versus-true values, the four modes, tuning, events.

Modelled: dq motor with temperature-dependent R, cogging, Coulomb and viscous
friction; dead time with its low-current knee; FET R_ds(on) rising with board
temperature; supply that cannot sink current (or a battery), its current limit
and lead resistance, ~60 µF of bus capacitance; 12-bit CSA codes with offset,
noise and an unsettled reading when the low-side window is too short; 21-bit
encoder with noise, read half a period early; TIM1 preload (duties act one
period late); DRV8353 VDS over-current latch and UVLO; NTC readings of the
board and winding temperatures.

Not modelled: diode rectification with the bridge off (a coasting motor whose
back-EMF exceeds V_bus pumps the bus on real hardware), magnetic saturation,
iron losses, CAN.

## What the simulation taught (worth checking on rev A)

- **Inductance test and dead time.** A square wave around zero current lets
  the dead time act on both sides of each zero crossing; the ramp is steeper
  before the crossing than after, so L read +4 % on the 2204. The test now runs
  on a DC bias (taken from the R test's intercept, which is the dead-time
  voltage), so the current never crosses zero. L is within 0.4 %.
- **Resistance at low current.** At the gimbal's 0.25/0.5 A test levels the
  dead-time voltage is still growing with current (the knee is ~0.2–0.3 A at
  24 V, from the FETs' C_oss), so ΔV/ΔI reads 3.5 % high. Dead-time
  compensation would fix it and smooth the gimbal at low speed.
- **Decoupling from the reference, not the step.** Feeding forward ω·L·i_ref
  applies the cross term before the current exists and pushed i_d by 2.3 A;
  the reference through a first-order model of the closed loop cuts it to 0.44 A.
- **The current loop is faster than its nominal 1.5 kHz.** kp = L·ωc with the
  1.5-period PWM delay gives a damped second-order response (0.10 ms rise, 2 %
  overshoot). Fine, but the "bandwidth" parameter is not the −3 dB point.
- **Current resolution.** 1 mΩ shunts at ×10 give 80 mA per ADC count (20 mA
  at ×40): visible in the 30 kHz capture at gimbal currents. Per-millisecond
  averages are clean.
