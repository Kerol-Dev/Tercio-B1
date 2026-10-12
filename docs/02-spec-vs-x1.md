# 2. Proposed spec versus moteus-x1

B1 numbers are **targets** until the bench tests in [08](08-bringup.md)
confirm them. Competitor numbers come from the vendor pages on 2026-10-12. The
x1 numbers are Kerol's; the research agent confirmed them on mjbots.com (the
docs give 23.8 g, the shop 23.7 g). The n1 and r4.11 are included because they
sit closest to the B1 on size and price.

| | **Tercio B1 (target)** | moteus-x1 | moteus-n1 | moteus r4.11 |
|---|---|---|---|---|
| Price, 1 unit | **$99–119** | $175 | $149 | $94 |
| Price, 100+ | to set after the rev C BOM (landed cost ≈ $25.50 at 100) | $155 | $129 | $78 |
| Supply | **10–52 V** (3S–12S, 48 V supplies) | 10–54 V | 10–54 V | 10–44 V |
| Peak phase current | **~80 A** design (publish after test) | 120 A | 100 A | 100 A |
| Continuous, uncooled | **15 A** target | 25 A | 9 A | 12 A |
| Continuous, cooled | heat-spreader option, rating after test | 62 A | 26 A | 32 A |
| Peak electrical power | published after test | 1.3 kW at 36 V | n/a | n/a |
| PWM | 15–60 kHz (default 30) | 15–60 kHz | 15–60 kHz | 15–60 kHz |
| Current loop | 15–40 kHz | 15–30 kHz | 15–30 kHz | 15–30 kHz |
| MCU | STM32G431 @ 170 MHz (CORDIC/FMAC) | STM32G4 @ 170 MHz | STM32G4 | STM32G4 |
| Gate driver | DRV8353RS (100 V class, VDS OCP, 3 CSAs) | n/a | n/a | n/a |
| Onboard encoder | **MT6835, 21-bit** absolute | AS5047P class, 14-bit | AS5047P, 14-bit | AS5047P, 14-bit |
| External encoder | Aux GH-8: SPI, I2C, quadrature (ABZ) | aux ports: SPI, I2C, quadrature, Hall, UART | same | same |
| Other inputs | Step/dir, RC PWM, GPIO, motor NTC | not checked (see mjbots docs) | not checked | not checked |
| Bus | CAN-FD **500k/2.5M and 1M/5M**, Tercio protocol v2 | CAN-FD 5 Mbit/s | CAN-FD 5 Mbit/s | CAN-FD 5 Mbit/s |
| Second host link | none (CAN only) | RS422 | RS422 | none |
| Data connectors | 2 × JST-GH 4 (daisy chain) + GH-8 aux | JST-PH3 + JST-GH aux | PH-3, GH aux | 2 × PH-3 |
| Power connector | 1 × XT30 + phase pads | XT30 | XT30PW | 2 × XT30 |
| Size | **46 × 46 mm**, height ≤ 10 mm target | 56 × 56 × 10 mm | 46 × 46 × 8 mm | 46 × 53 mm |
| Mass | ≤ 16 g target | 23.7 g | 14.6 g | 14.2 g |
| Firmware | Apache-2.0 | Apache-2.0 | Apache-2.0 | Apache-2.0 |
| Host tool | **Tercio Control in the browser** (no install, via the FD) | tview (Python desktop app) | same | same |
| Libraries | Python, Arduino/C++; **same API as the S1 stepper** | Python, C++, Rust, Arduino | same | same |
| Cooling accessories | heat-spreader plate (rev B option) | fan, heat spreader | yes | yes |
| Same-bus steppers and IMU | **S1, IMU, FD** | no | no | no |

## Reading the table

- **Ahead:** price against x1 and n1, uncooled continuous against n1 and
  r4.11, encoder resolution, browser tool, stepper + IMU on the same bus,
  supply range against r4.11.
- **Level:** PWM and loop rates, MCU class, CAN-FD 5 Mbit/s (once the 1M/5M
  profile ships), open firmware.
- **Behind:** peak current against all three, cooled continuous against x1,
  no RS422/second host link, no Hall input at release, younger firmware.
- **To prove on the bench before any of this goes on a web page:** 15 A
  uncooled, 80 A peak duration, loop rate at 40 kHz on the G431, MT6835 noise
  after calibration.
