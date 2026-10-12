# 7. Firmware plan

Status: plan, 2026-10-12. Nothing here is written yet.

The brushless firmware is the S1 firmware with a different real-time core. The
protocol, CAN driver, flash store, clock check, trajectory planner, parameter
system, state machine pattern and host-test setup carry over. What is new is
the FOC core, the power-stage drivers, the calibration and identification
procedures, and a host-side motor simulator that lets most of this be tested
before a board exists.

## 7.1 Ground rules (carried from the S1 and IMU firmware)

- PlatformIO, `platformio/ststm32@20.0.0`, STM32duino core plus HAL, no
  third-party libraries. `-O2`, `-Wdouble-promotion`, float32 only in
  interrupts.
- The control loop is independent of the main loop: the main loop can stall
  (flash erase, a slow host) without touching the current loop.
- Hardware-independent modules build for `[env:native]` and are tested with
  `pio test -e native`.
- `Protocol.h` stays the wire contract; host libraries mirror it and are
  cross-checked byte for byte.
- Hardware facts live in `board/Board.h` only (pins, shunt value, CSA gain,
  divider ratios, NTC beta).

**MCU: STM32G431CBT6 (decided).** It is the same chip, board file
(`genericSTM32G431CB`), core variant and HSE setup as the S1 and IMU, so the
build configuration carries over line for line. 128 KB flash, 32 KB SRAM
(including 10 KB CCM SRAM for the ISR), CORDIC and FMAC. The S1 build is
64 KB today, so budget flash from the start: bootloader ~10 KB, application
≤ 110 KB, FlashStore pages at the end. The pin-compatible G474CBT6 alternate
would need its own board JSON (copy the local `weact_g474ceu6.json`); a G474
with 512 KB is not affordable at the moment ([03](03-parts.md)).

## 7.2 Real-time structure

```
 TIM1 centre-aligned PWM (default 30 kHz)
   │ CH4 compare at the counter peak ──► start encoder SPI read (DMA)
   │ TRGO2 at the counter valley (all low-side FETs on)
   ▼
 ADC1 + ADC2 dual simultaneous injected:  rank 1 = I_A | I_B   rank 2 = I_C | V_BUS
   │ JEOS interrupt, priority 0  ──► FocTick (target ≤ 8 µs at 170 MHz)
   ▼
  1. currents and bus voltage to SI units (offsets from the last zeroing)
  2. encoder sample (already in RAM via DMA): unwrap, linearity table,
     latency compensation θ += ω·1.5·T_pwm
  3. Clarke / Park (CORDIC sin and cos)
  4. d/q current PI with decoupling feed-forward, voltage-circle limit, anti-windup
  5. inverse Park, SVPWM (min-max injection), write TIM1 CCR1..3 (preloaded)
  6. every N ticks: outer loop (position/velocity PD + feed-forward → i_q ref)
     and the S1 trajectory planner (Q32.32 turns)
  7. per-tick protection: software overcurrent, bus OV/UV, encoder age
 Main loop (as S1): Node (CAN) · Axis @ 1 kHz · procedures · thermal model ·
   driver SPI monitor (through a mailbox the ISR serves) · FlashStore
```

Time budget at 30 kHz (33.3 µs per tick): ADC conversion ~1 µs, FocTick target
≤ 8 µs (ISR code and data in CCM SRAM), outer loop ≤ 3 µs, leaving well over
half the CPU to the main loop. At 40 kHz (25 µs) the same budget is ~45 %
load. Measure it on the ESC1 in F1 before promising 40 kHz. The control-loop load stays in telemetry
(`loadPct`), as on the S1. PWM is configurable 15–40 kHz. The current loop
runs at the PWM rate, so 15–40 kHz too.

## 7.3 Module map: reuse versus new

| Module | Source | Action |
|---|---|---|
| `protocol/Protocol.h` | S1 | Extend (device class 2, new commands, params and frame type, see 7.5) |
| `drivers/CanBus` | S1 | Copy unchanged. FDCAN1 on PA11/PA12, same timing as S1/FD/IMU |
| `drivers/FlashStore`, `Crc32` | S1 | Copy unchanged (same G431, 2 KB pages) |
| `board/Clock`, `Nmi` | S1 | Copy (16 MHz HSE checked against HSI, HSI fallback) |
| `control/Trajectory`, `Fixed` | S1 | Copy unchanged |
| `control/EncoderTracker` | S1 | Reuse for the velocity PLL. Re-check the Q formats for 21-bit counts and 30 kHz |
| `app/Node` | S1 | Adapt: same dispatch, new command table |
| `app/Params`, `Settings` | S1 pattern | New parameter table |
| `app/Axis` | S1 pattern | New state machine with torque and impedance modes, same fault policy |
| `app/Procedures` | S1 pattern | New procedures (7.6). `Homing` is reused almost as is |
| `drivers/PowerStage` | new | TIM1 complementary PWM, dead time, break input, ADC sync, offset zeroing |
| `drivers/Drv83xx` | new | SPI configuration, fault decode, CSA gain/offset calibration |
| `encoder/Mt6835` | new | SPI1 mode 3 with DMA (≤ 16 MHz), status bits, CRC once confirmed in the datasheet, magnet-strength warnings |
| `encoder/aux*` | new + S1 | Aux port: SPI absolute (AS5047/MT68xx), I2C (S1's AS5600 driver), quadrature and step/dir (TIM2) |
| `foc/` | new | Transforms, SVPWM, current controller, observers. Pure C++, host-testable |
| `sim/` (host only) | new | Motor, inverter, sensing and encoder models (7.7) |

The IMU repo already copies CanBus, FlashStore, Clock and Crc32 from the S1.
A third copy is the point to extract a shared `tercio-common` (git submodule or
PlatformIO `lib/`). **Do that after 1 December** so the S1 repo does not change
before launch. Until then the brushless repo copies the files, as the IMU did.

## 7.4 Control modes

| State (`AxisState`) | Meaning on the brushless driver |
|---|---|
| Disabled (0) | Bridge off (all FETs off, driver ENABLE low) |
| Holding (1) | Position hold on the outer loop |
| Moving (2) | Trajectory move (`MoveTo`/`MoveBy`, same planner as S1) |
| Velocity (3) | Velocity mode (`SetVelocity`) |
| StepDir (4) | Follows step/dir from the aux port (TIM2 clock+direction mode) |
| Calibrating (5) / Homing (6) / Tuning (7) | Procedures |
| Fault (8) | Latched hard fault, bridge off |
| **Torque (9)** *(new)* | Direct torque/current command with a velocity limit |
| **Impedance (10)** *(new)* | τ = kp·(p* − p) + kd·(v* − v) + τ_ff, set by one frame per cycle (the legged-robot command) |

The host-visible API (`move_to`, `set_velocity`, `wait_settled`, telemetry
position and velocity in turns) behaves exactly as on the S1, so a script
written for a stepper axis drives a brushless axis unchanged.

## 7.5 Protocol additions (proposal; stays protocol v2)

All additions are new opcodes, parameter ids and a new frame type. An S1
receiving them answers `UnknownCommand`/`UnknownParam` as it does today, so
mixed buses keep working.

- `kDeviceBldc = 2` (last byte of GetInfo).
- **Commands**
  - `SetTorque 0x18`: `[f32 torque Nm][f32 max velocity, optional]`.
  - `Impedance 0x19`: `[f64 position][f32 velocity][f32 kp][f32 kd][f32 torque ff]` (25 bytes, padded to 32).
  - `MeasureMotor 0x23`: R, L, flux linkage (7.6).
  - `Calibrate 0x20` is reused. On this device it does the encoder offset, direction, pole pairs and linearity table.
  - `AutoTune 0x22` is reused. Here it sets the current-loop gains from R and L, then tunes the velocity and position gains.
- **Parameters, new range 0x80–0xBF**: PolePairs, PhaseResistance,
  PhaseInductance (d, q), TorqueConstant, MaxPhaseCurrent, MaxBusCurrent,
  MaxRegenCurrent, BusOverVoltage, BusUnderVoltage, CurrentLoopBandwidth,
  PwmFrequency, PositionKp/VelocityKd/Ki (in Nm units, deliberately separate
  from the S1's 0x22–0x24), VelocityPllBandwidth, EncoderSource,
  OutputEncoderSource, MotorThermistorBeta, MotorOverTemperature,
  FetOverTemperature, DerateStart. The S1 ids for MaxVelocity,
  MaxAcceleration, GearRatio, limits, homing and timeouts are reused with the
  same meaning.
- **Telemetry**: frame 0x01 stays byte-identical (37 bytes), so every existing
  host, panel view and library shows position, velocity, state, faults,
  temperature and supply without changes. A new optional frame
  `kFrameDrive = 0x04` carries i_q, i_d, v_q, v_d, bus current, FET and motor
  temperature, the raw encoder value and a torque estimate (~32 bytes). It has
  its own rate parameter.
- **Faults**: bits 9–14 (free today) for OverVoltage, UnderVoltage,
  OverCurrent, MotorOverTemperature, OutputEncoder and PhaseLoss. The existing
  bits keep their meaning: DriverFault means driver nFAULT, DriverComm means
  driver SPI, Encoder means the onboard encoder.

### Bus budget at 500 kbit/s / 2.5 Mbit/s (from `tools/can_budget.py`)

| Traffic per node per cycle | Bus time per node | Nodes at 1 kHz | at 500 Hz | at 250 Hz |
|---|---:|---:|---:|---:|
| Telemetry only (today's 38-byte frame) | 266 µs | 2 | 5 | 10 |
| MoveTo command + telemetry | 440 µs | 1 | 3 | 6 |
| Impedance command + compact reply | 378 µs | 1 | 3 | 7 |

(At or below 70 % bus load, with pessimistic stuffing.) At 1 Mbit/s / 5 Mbit/s
every number roughly doubles: 3 nodes at 1 kHz, 7 at 500 Hz. The 500 kbit/s
arbitration phase dominates short frames. So:

- Arms, gimbals, pan-tilts and mixed stepper/brushless machines (≤ 3 joints at
  500 Hz, or ≤ 6 at 250 Hz) fit one 2.5M bus.
- Legged robots (8–12 joints at 1 kHz) do not fit one bus at either rate.
  moteus users solve this with several buses (the pi3hat has 4). The Tercio
  answers would be one FD adapter per limb, a later multi-channel adapter, and
  a grouped broadcast setpoint frame (several joints in one 64-byte frame).
  The grouped frame is a protocol-design item for after the first release.

### Bus profiles: 500k/2.5M and 1M/5M (decided: both, from the B1's first release)

- A persisted `BusProfile` parameter (0 = 500k/2.5M, the default; 1 = 1M/5M)
  on every node: B1, S1, FD and IMU. All four use the G4 FDCAN at the same
  kernel clock, so each profile is one more timing table (prescaler, segments
  and transceiver-delay compensation, as `CanBus` already sets for 2.5M).
- Switching is a **two-phase broadcast**. First `PrepareBusProfile [profile]
  [token]`: every node acknowledges. Then `CommitBusProfile [token]`: nodes
  restart at the new rate. A node that sees no valid frame within ~5 s at the
  new rate reverts to the old profile and reports it. A bus can never be left
  half-switched with silent nodes.
- The FD adapter follows the same command, so Tercio Control can switch a
  whole bus with one button.
- Verify the MCP2562FD at 5 Mbit/s on a 1–2 m GH daisy chain with 4–6 nodes
  (bring-up stage 13). The TJA1462 is the fallback if ringing shows up.
- No S1 units are built yet, so the S1 shipping firmware can carry the
  profile from day one ([09](09-risks-schedule.md) §9.1). Same for the FD
  (which also updates over ROM USB DFU) and the IMU.

## 7.6 Calibration and identification (procedure state machines, ~1 kHz)

Each one runs as a non-blocking state machine, as on the S1. It can be
aborted, reports `procedureStep` in telemetry, and saves its result through
FlashStore.

1. **Sense offsets**: bridge off, average 1024 samples per CSA. Repeated at
   every enable.
2. **Phase resistance**: closed current loop on the d axis at θ = 0 and two
   current levels. R comes from the slope ΔV/ΔI, which cancels the dead-time
   voltage error.
3. **Phase inductance**: d-axis voltage square wave at a few kHz. L = V / (di/dt),
   averaged over many cycles.
4. **Direction and pole pairs**: open-loop electrical rotation, N electrical
   turns at the calibration current. Pole pairs = round(N / mechanical turns);
   direction from the sign.
5. **Encoder offset**: lock the rotor at 8–16 electrical angles, forward then
   backward, and average to cancel friction.
6. **Linearity table**: slow spin in both directions, comparing the encoder
   with the commanded electrical angle, giving a 128-point table (magnet
   eccentricity, sensor nonlinearity).
7. **Flux linkage / Kv**: closed-loop spin at a set speed.
   λ = (v_q − R·i_q) / ω_e, Kt = 1.5 · pp · λ.
8. **Current-loop gains**: kp = L·ω_c, ki = R·ω_c, with ω_c = 2π · bandwidth
   (default 1.5 kHz at 30 kHz PWM). Verified by a current step; rise time and
   overshoot are reported.
9. **Optional**: inertia and friction (a known-torque acceleration test) for
   feed-forward.

Tercio Control turns 1–8 into a wizard with live plots. That is the hands-on
part of the ecosystem pitch: plug in, click Calibrate, get a tuned joint.

### Protection layers

| Layer | Mechanism | Reaction time |
|---|---|---|
| Hardware | Driver VDS overcurrent and sense-overcurrent → nFAULT → TIM1 BKIN | < 1 µs, PWM off without the CPU |
| Hardware | Driver UVLO, charge-pump and thermal faults | driver-internal |
| Per tick | Software overcurrent on the measured phase currents | 1 PWM period |
| Per tick | Bus overvoltage: limit regen current, then fault | 1 period |
| Per tick | Encoder sample age and CRC | 1 period → fault after N bad samples |
| 1 kHz | FET NTC, motor NTC and I²t thermal model → derating, then fault | ms |
| 1 kHz | CAN command timeout (deadman) also for velocity, torque and impedance modes | configurable |

The deadman fixes the open item from the S1 control panel
(`CommandTimeoutMs` defaults to 0). On a brushless joint the default should
not be "keep spinning".

**Regen policy.** A bench supply cannot absorb current. Enforce
`MaxRegenCurrent` (estimated bus current = 1.5 · (v_d·i_d + v_q·i_q) / V_bus)
and clamp braking torque while V_bus rises above `BusOverVoltage − margin`.
The simulator tests this (7.7, test 7).

## 7.7 Host-side simulation, before any hardware

`sim/` is host-only C++ built in `[env:native]`. The FOC core under test is the
same source the MCU compiles. The core's interface is
`FocCore::tick(const Sample&) -> Duty`, with no HAL inside.

| Model | Contents |
|---|---|
| Motor | dq PMSM: R, L_d, L_q, λ, pole pairs, J, viscous and Coulomb friction, cogging harmonics, load-torque profile. RK4 at 32 sub-steps per PWM period |
| Inverter | Average model (duty × V_bus) for fast tests; switching model with dead time and diode conduction for detailed ones |
| Bus | Source with internal resistance and a "cannot sink" option, bus capacitance, so regen pump-up is real |
| Sensing | Shunt × CSA gain, offset, noise, 12-bit quantisation, sampled at the valley; low-side-window rule at high modulation |
| Encoder | MT6835 21-bit quantisation, noise, eccentricity harmonic, SPI latency, CRC-error and magnet-loss injection |
| Driver | nFAULT and VDS-OCP injection |

**Unity tests** (all host-side, run in CI later):

1. Clarke/Park/SVPWM against reference values; SVPWM never exceeds the
   linear-region limit.
2. Current step on i_q: 10–90 % rise within the bandwidth target, overshoot
   < 5 %, zero steady-state error.
3. Decoupling at speed: i_d stays near 0 while i_q steps at 50 % base speed.
4. Calibration finds pole pairs, direction and offset for a seeded set of
   motors (gimbal ~10 Ω/3 mH, 5010-class ~0.2 Ω/80 µH, 2204 hobby).
5. R, L and λ identification within 5 % on the same set, including the
   dead-time model.
6. Position step and trajectory tracking through the S1 planner.
7. Regen: braking a high-inertia load on a supply that cannot sink keeps V_bus
   under the OV limit.
8. Faults: encoder dropout → Fault within 1 ms; injected overcurrent → PWM off
   within one tick; command timeout → stop.
9. Protocol codec tests for the new frames, mirrored in the Python and JS
   libraries (as the S1 does today).

A small `tools/plot_sim.py` turns the simulator's CSV output into plots for
eyeballing step responses and calibration sweeps.

## 7.8 Real hardware before our own board

Develop the FOC core on an off-the-shelf board while our PCB is in fab: the
ST **B-G431B-ESC1** (STM32G431 with a 3-phase power stage and op-amp current
sensing). PlatformIO already has `disco_b_g431b_esc1`. Pair it with a magnetic
MT6835 breakout and one of your test motors. Price is
about $20; check stock before ordering. Check whether its CAN pins have a
transceiver fitted. If not, use a breakout with an MCP2562FD, the same
transceiver as the FD. This gets FOC working on a real motor without our
power stage being a suspect.

## 7.9 Tercio Control and libraries

- **Tercio Control**: an `assets/bldc.js` page next to `imu.js`, picked by
  device class 2. It has the calibration and identification wizard, live
  i_q/i_d/velocity/position plots from frame 0x04, and tuning. `sim.js` gets a
  simulated brushless node (a JS port of the average model) so the demo mode
  keeps working.
- **Python and Arduino**: a `Brushless` class with the same method names as
  `Stepper` (`enable`, `move_to`, `set_velocity`, `telemetry`,
  `wait_settled`, `calibrate`), plus `set_torque`, `impedance`,
  `measure_motor`, and a shared axis interface so code can swap an S1 for a
  brushless joint.
- **Docs site**: a product section generated from the same data files as the
  S1 and IMU pages.
- **Firmware update over CAN**: needed for any multi-joint robot, where
  reflashing joints one by one over SWD is not acceptable. On the G431 that
  means a ~10 KB CAN bootloader that stays put, plus a ≤ 110 KB application
  slot verified by CRC32 before every jump. The S1 build is 64 KB today, so
  this is comfortable but not roomy. The same bootloader could later be
  installed on the S1 (G431 too) to fix its SWD-only update path.

## 7.10 Firmware milestones

| Id | Milestone | Needs hardware? |
|---|---|---|
| F0 | `foc/` + `sim/` + tests 1–6 green | no |
| F1 | FOC on the B-G431B-ESC1 with a test motor: current loop, open-loop spin, calibration | dev board |
| F2 | Own board rev A bring-up firmware (see [08-bringup.md](08-bringup.md)) | rev A |
| F3 | Identification, linearity table, auto gains on rev A | rev A |
| F4 | Protocol additions, Python/Arduino `Brushless`, Tercio Control page | rev A |
| F5 | Fault injection on hardware, thermal runs, 24 h soak, CAN update | rev B |
| F6 | Release candidate, docs, factory test firmware | rev B/C |
