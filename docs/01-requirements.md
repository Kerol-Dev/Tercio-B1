# 1. Requirements and the wedge

Status: decided with Kerol on 2026-10-12. Items marked *open* are still to
decide; see the [decision log](../README.md#decision-log).

## 1.1 What the Tercio B1 is

A small field-oriented-control driver for brushless motors. It joins the S1
(steppers), the FD (USB-C to CAN-FD) and the IMU on the same CAN-FD bus,
protocol, browser panel and libraries. It competes with the mjbots moteus-x1
on the ecosystem and on value, not on raw peak power.

## 1.2 Decisions so far

| Topic | Decision |
|---|---|
| Power class | Smaller class first: 10–52 V operating (3S–12S LiPo, 12/24/36/48 V supplies) |
| Current | Designed for ~80 A peak phase current; 15 A continuous without cooling is the target. Ratings get published only after bench tests (see 1.5) |
| Target motors | Gimbal motors, QDD 5010/6010 class, small drone/hobby outrunners (2204–2814). 8108-class motors work, current-limited |
| Price | $99–119 single unit |
| Size | ~46 × 46 mm square, 4 × M2.5 |
| Position sensing | Onboard absolute magnetic encoder **plus** an aux port for an output-side encoder (geared joints) |
| Onboard encoder | MagnTek/NOVOSENSE **MT6835**, 21-bit |
| MCU | **STM32G431CBT6**, the same chip, core variant and board file as the S1 and IMU. The G474CBT6 stays a pin-compatible alternate |
| Gate driver | TI **DRV8353RS**: 100 V class, SPI, three current-sense amplifiers, integrated buck |
| CAN connector | 2 × JST-GH 4-pin, daisy-chain |
| Power connector | 1 × XT30 + solder pads for the motor phases |
| Extras | Motor thermistor input, PWM and step/dir input, spare GPIO/analog, all on one aux JST-GH 8-pin |
| USB | None. The FD adapter is the one way in |
| Bus | CAN-FD, protocol v2. 500 kbit/s / 2.5 Mbit/s **and** a 1 Mbit/s / 5 Mbit/s profile, both supported from the first release |
| Firmware licence | Apache-2.0 (same as moteus, with a patent grant) |
| Name | **Tercio B1** (working name) |
| KiCad flow | Code owns everything: schematic, placement, power-stage copper and routing are regenerated every spin |
| Timing | Schematic work starts now, in parallel with the S1/FD launch (1 Dec 2026). Guardrails in [09](09-risks-schedule.md) |

## 1.3 Functional requirements

| Id | Requirement | Verified by |
|---|---|---|
| R1 | Drive a 3-phase PMSM/BLDC with FOC from an absolute magnetic encoder | Bring-up stage 6 |
| R2 | Phase current up to 80 A for short bursts, configurable limit | Locked-rotor test (stage 10) |
| R3 | 15 A RMS continuous at 25 °C still air, FET case ≤ 100 °C (target; the published rating follows the test) | Thermal run (stage 9) |
| R4 | Supply 10–52 V; overvoltage fault ≤ 58 V; undervoltage fault ~9 V | Bench |
| R5 | Bus overvoltage protection with a regen limit when the supply cannot sink current | Regen test (stage 11) + sim test 7 |
| R6 | Current loop at 15–40 kHz, PWM 15–60 kHz (default 30 kHz) | Loop-load telemetry |
| R7 | Onboard 21-bit encoder; aux port for SPI/I2C absolute, quadrature, step/dir, RC PWM | Aux bring-up |
| R8 | CAN-FD protocol v2, device class 2. Same `MoveTo`/`MoveBy`/`SetVelocity`/`Sync`/telemetry semantics as the S1, plus torque and impedance commands | Host tests + library cross-checks |
| R9 | Runs 500k/2.5M and 1M/5M; switching all nodes is a safe, recoverable operation | Mixed-bus test with S1 + FD |
| R10 | One-click calibration (encoder offset, pole pairs, direction, linearity) and motor identification (R, L, flux linkage) | Wizard in Tercio Control |
| R11 | Protection: driver VDS OCP → hardware PWM off; software OCP; OV/UV; FET and motor temperature derating; encoder fault; CAN command timeout in every motion mode | Fault injection (stage 12) |
| R12 | Firmware update over CAN (multi-joint robots can't be reflashed by SWD one by one) | Release criterion |
| R13 | Tercio Control page, Python and Arduino `Brushless` classes, docs-site product section | Release criterion |
| R14 | Board-level hardware lessons from the S1/FD applied: BOOT0 pull-down, NRST cap, VBAT connected, SWD with GND, driver enable pulled to "off", no supply rail on bus connectors | Schematic review checklist |

## 1.4 The wedge

The competition research (vendor pages, 2026-10-12) changed the framing. The
nearest threat to a $99–119, 46 mm board is not the x1. It is mjbots' own
**moteus-n1** (46 × 46 mm, 10–54 V, 100 A peak, 9 A continuous uncooled, $149,
$129 at 100+) and the **moteus r4.11** ($94, 10–44 V, 100 A peak, 12 A
uncooled). The x1 is the halo product.

**Where the B1 wins:**

1. **One bus, one panel, one library for steppers *and* brushless.** No
   competitor covers steppers. A user with an S1 on a linear axis and B1s on
   the joints writes one Python script with one API (`move_to`,
   `set_velocity`, telemetry in turns). One browser panel discovers every node
   on the bus. "Browser panel" alone is no longer unique: ODrive has one over
   USB, and Tinymovr shipped one over CAN in August 2026. The *combination*
   is the claim.
2. **Continuous current per dollar.** 15 A uncooled (if the bench confirms it)
   beats the n1 (9 A) and the r4.11 (12 A) at a lower price. Lead with
   continuous, quote it under the same conditions mjbots uses, and do not lead
   with peak.
3. **48 V in 46 mm under $120.** That slot is open: the r4.11 stops at 44 V,
   and the n1 is $149.
4. **Resolution headline.** The MT6835 is 21-bit against the 14-bit AS5047P on
   every moteus. Worth stating only next to measured noise and linearity after
   calibration.
5. **First-unit cost.** moteus needs a $39 adapter; the Tercio path is a B1
   plus the FD. Price a starter bundle (B1 + FD + GH cables + magnet) against
   "n1 + mjcanfd".
6. **Open firmware (Apache-2.0)**, as moteus. That is table stakes;
   ODrive is the closed outlier.

**Where the B1 must not compete:**

- Peak-amp marketing against the n1/x1 (100–120 A).
- Price-fighting with the sub-$35 boards (SimpleFOC, MKS): no CAN-FD, no
  onboard encoder, thin docs. Use them as the "what a polished board adds"
  contrast.
- Legged robots at 1 kHz on one bus. No single CAN bus does that; see the bus
  budget in [07-firmware.md](07-firmware.md), §7.5.

**Starting assumption confirmed:** the strongest wedge is the ecosystem. The
spec only has to be *credibly* in class (voltage range, continuous current,
encoder quality) so that the ecosystem decides the purchase.

## 1.5 How ratings get published

mjbots publishes "uncooled" and "with thermal management" numbers. The B1's
rating method must match so comparisons hold:

- **Continuous:** 25 °C ambient, still air, board horizontal, motor at locked
  rotor or on the dyno. The rating is the RMS phase current at which the
  hottest FET case settles at 100 °C, with a 10 % margin taken off.
- **Cooled:** the same, with the optional heat-spreader plate on a defined
  aluminium surface.
- **Peak:** current and duration (e.g. 80 A for 1 s from a 25 °C start), both
  stated.

## 1.6 Out of scope for the first release

- Hall-sensor motors (the aux port has enough pins; firmware later if asked)
- Sensorless control (phase-voltage divider footprints are on rev A, not fitted)
- Field weakening
- RS-485/RS-422, USB
- Brake resistor output (consider for rev B if regen testing shows a need)
