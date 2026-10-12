# Tercio B1: brushless FOC driver (planning)

Working name **Tercio B1**. A 46 × 46 mm field-oriented-control driver for
brushless motors, 10–52 V, designed for ~80 A peak and targeting 15 A
continuous without cooling. It has an onboard 21-bit MT6835 encoder plus an
aux encoder port, and CAN-FD on Tercio protocol v2 (device class 2). It sits on
the same bus, panel and libraries as the Tercio S1 stepper driver, the FD
adapter and the IMU. It competes with the mjbots moteus-x1 (and, closer in
size and price, the moteus-n1) on the ecosystem and on value.

**Status:** planning only (2026-10-12). No schematic, layout or firmware yet.
The S1/FD launch on 1 December 2026 comes first; see the guardrails in
[docs/09](docs/09-risks-schedule.md).

## Documents

| # | Document | Contents |
|---|---|---|
| 1 | [Requirements and the wedge](docs/01-requirements.md) | Decisions, functional requirements, positioning against moteus/ODrive, rating method |
| 2 | [Spec versus moteus-x1](docs/02-spec-vs-x1.md) | Side-by-side with x1, n1 and r4.11 |
| 3 | [Part shortlist](docs/03-parts.md) | Live LCSC/JLCPCB stock and prices (2026-10-12), choices and alternates |
| 4 | [Block diagram and pin map](docs/04-architecture.md) | Power tree, STM32G431 pin map, TIM1/ADC sync, aux and CAN connectors, floor plan |
| 5 | [BOM cost and PCB plan](docs/05-bom-pcb.md) | ≈ $45/board at 10, ≈ $25.50 at 100 (landed); 4-layer 2 oz stackup and layout rules |
| 6 | [KiCad as code](docs/06-kicad-as-code.md) | Python-generated schematic and board, Freerouting, kicad-cli checks and outputs |
| 7 | [Firmware plan](docs/07-firmware.md) | S1 architecture reuse, FOC core, calibration/identification, protocol additions, bus profiles, host simulator |
| 8 | [Bring-up and test plan](docs/08-bringup.md) | Equipment, regen handling, 14 staged tests with pass criteria |
| 9 | [Risks and schedule](docs/09-risks-schedule.md) | Risk register; 3 spins; launch ~June 2027; ≈ $4,000–4,500 to launch |

## Data and tools

| Path | What |
|---|---|
| `tools/parts_lookup.py` | Live JLCPCB + LCSC stock and price lookup (standard library only). Reads `tools/candidates*.txt` |
| `tools/bom_estimate.py` | BOM cost at 10/100 boards from the lookup data → `data/bom-estimate.csv` |
| `tools/can_budget.py` | CAN-FD bus-time budget per node and rate (`python3 tools/can_budget.py 1000000 5000000`) |
| `data/parts-live-2026-10-12*.csv` | 686 rows of live part data from 2026-10-12 |
| `data/pinmap-g431cbt6.csv` | Pin map as a table, for the generator |

Re-run before any order (stock moves daily):

```bash
cd ~/Documents/Projects/Tercio-bldc && python3 -I tools/parts_lookup.py && python3 -I tools/parts_lookup.py tools/candidates-extra.txt && python3 -I tools/bom_estimate.py
```

## Decision log

Decided with Kerol on 2026-10-12:

| Topic | Decision |
|---|---|
| Power class | Smaller class first → 10–52 V (DRV8353RS makes 12S/48 V possible) |
| Peak current | Design for ~80 A peak; lead marketing with continuous current |
| Target motors | Gimbal, QDD 5010/6010, small drone/hobby BLDC |
| Price | $99–119 |
| Size | ~46 × 46 mm |
| Encoder | Onboard MT6835 (21-bit) + aux port for an output-side encoder |
| MCU | STM32G431CBT6 (G474CBT6 as a pin-compatible alternate) |
| Gate driver | DRV8353RS |
| CAN connector | 2 × JST-GH 4-pin, daisy chain |
| Power connector | 1 × XT30 + motor solder pads |
| Extras | Motor thermistor, PWM and step/dir input, spare GPIO/analog |
| USB | No (CAN only, via the FD) |
| Bus | 500k/2.5M and 1M/5M, both from the B1's first release |
| Licence | Apache-2.0 |
| Name | Tercio B1 (working name) |
| KiCad flow | Code owns everything, including routing |
| Timing | Start the schematic now, in parallel with the launch |
| S1 and the 1M/5M bus | No S1s are built yet: the shipping firmware carries the bus profile |
| Repository | Private GitHub repo Kerol-Dev/Tercio-bldc |

Still open:

| Topic | Notes |
|---|---|
| Weekly time cap before launch | Yours to set; the schedule assumes part-time |
| Electrolytic on board vs on the XT30 pigtail | Height (10 mm) vs cable damping; decide at layout |
| Mounting-hole pattern | Pick against the 5010/6010 motors at layout |
| Retail price inside $99–119, volume tiers, starter bundle | After rev B, when the BOM and ratings are firm |
