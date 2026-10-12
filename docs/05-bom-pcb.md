# 5. BOM cost estimate and PCB plan

## 5.1 BOM at 10 and 100 boards

Produced by [`tools/bom_estimate.py`](../tools/bom_estimate.py) from the live
price data of 2026-10-12 (`data/bom-estimate.csv`). Lines with an LCSC code use
real JLC price breaks for the total quantity (per-board qty × boards). "est"
lines are lumped Basic passives at typical prices.

| Refs | Part | LCSC | JLC stock | Qty | $/board @10 | $/board @100 |
|---|---|---|---:|---:|---:|---:|
| U1 | STM32G431CBT6 | C529355 | 5241 | 1 | 4.38 | 4.05 |
| U2 | DRV8353RSRGZR | C506246 | 1675 | 1 | 5.24 | 4.61 |
| U3 | MT6835GT-STD-R | C2932578 | 1462 | 1 | 4.29 | 3.54 |
| U4 | MCP2562FDT-E/SN | C511335 | 5333 | 1 | 1.44 | 1.12 |
| U5 | TLV75533PDBVR | C404027 | 132914 | 1 | 0.14 | 0.11 |
| Q1–Q6 | BSC030N08NS5 | C501507 | 24529 | 6 | 4.61 | 3.41 |
| R1–R3 | 1 mΩ 2512 shunt RLP25FEGR001 | C459678 | 27351 | 3 | 0.27 | 0.21 |
| C1–C10 | 4.7 µF 100 V 1210 | C381466 | 160984 | 10 | 1.86 | 1.86 |
| C11 | 47 µF 80 V 10×10 electrolytic | C249920 | 7438 | 1 | 0.22 | 0.18 |
| D1 | SMBJ54A | C2891330 | 6025 | 1 | 0.04 | 0.04 |
| Y1 | 16 MHz crystal (Basic) | C13738 | 152708 | 1 | 0.09 | 0.07 |
| RT1 | NTC 10 k 0603 | C13564 | 178011 | 1 | 0.05 | 0.04 |
| D2 | PESD2CAN | C2687131 | 658668 | 1 | 0.04 | 0.04 |
| D3, D4 | TPD4E05U06DQAR | C138714 | 102774 | 2 | 0.17 | 0.13 |
| J1 | XT30PW-M | C431092 | 72882 | 1 | 0.33 | 0.26 |
| J2, J3 | JST SM04B-GHS-TB | C189895 | 28981 | 2 | 0.61 | 0.54 |
| J4 | JST BM08B-GHS-TBT | C133062 | 1233 | 1 | 0.37 | 0.30 |
| LED1, LED2 | 0603 LEDs (Basic) | C2286 | 7.1 M | 2 | 0.01 | 0.01 |
| — | DRV buck passives (inductor, 100 V Schottky, caps, FB divider) | est | | 1 | 0.30 | 0.22 |
| — | DRV support caps (100 V charge-pump caps, VGLS/DVDD/VCP, VM bypass) | est | | 1 | 0.10 | 0.07 |
| — | Logic passives (~50 × 0402, CAN split termination, dividers, filters) | est | | 1 | 0.18 | 0.12 |
| — | Leg HF decoupling 100 nF 100 V 0603 ×6 | est | | 1 | 0.05 | 0.03 |
| | **Components** | | | | **24.79** | **20.98** |

| Per board | 10 boards | 100 boards | Assumption |
|---|---:|---:|---|
| Components | 24.79 | 20.98 | live prices above |
| PCB | 5.00 | 1.60 | 4-layer 46 × 46 mm, 1.6 mm, 2 oz outer / 1 oz inner, ENIG, plugged vias under pads |
| Assembly, fixed fees spread | 10.80 | 1.08 | two-sided standard assembly setup (2 × $25), ~18 unique Extended parts × $3, through-hole setup (XT30) |
| Assembly, per board | 1.20 | 0.90 | solder joints, XT30 through-hole, handling |
| Shipping (no duties) | 3.50 | 0.90 | express to the EU |
| **Landed cost per board** | **≈ 45** | **≈ 25.50** | |
| Order total | ≈ $450 | ≈ $2,550 | |

PCB and assembly lines are **assumptions**; the JLC quote API needs a login.
Get a real quote with the rev A Gerbers before trusting them. Not included:
import duties/VAT, cables (GH-4 ×2, GH-to-bare wire), magnet, packaging,
payment fees, the test fixture, and scrap.

**Margin check:** at $109 retail and ~$26 landed cost (100 units), the
hardware gross margin before shop and payment fees is ~75 %, in line with
small-run electronics. The sensitivities are the DRV8353RS ($4.61), the
MT6835 ($3.54), the MCU ($4.05) and the six FETs ($3.41), together 75 % of
component cost. A cost-down rev (MT6826S, G474CBT6 if stocked, GH-compatible
aux connector) saves ~$2.

## 5.2 PCB plan

### Stackup (4 layers, 1.6 mm)

| Layer | Copper | Use |
|---|---|---|
| L1 top | 2 oz (70 µm) | Power stage (FETs, shunts, bulk MLCCs), DRV8353, MCU, connectors. V_BUS / phase / GND pours |
| L2 | 1 oz | **Solid GND**: reference for everything and the return for the power loop directly under L1 |
| L3 | 1 oz | V_BUS plane under the power stage, low-speed signals elsewhere |
| L4 bottom | 2 oz | MT6835 + decoupling (under the shaft), GND and phase pours as heat spreaders, extra current paths |

Use JLC's standard 4-layer impedance stackup (e.g. JLC04161H-7628, so the
prepreg between L1 and L2 is thin and the power-loop inductance stays low).
CAN and SPI need no controlled impedance at these lengths. Check at order
time, on JLC's capabilities page, that 2 oz outer + 1 oz inner is available
for 4-layer, and its minimum trace/space for 2 oz outer (it is coarser than
for 1 oz; QFN-48 0.5 mm pitch escape may need to run on L3).

### Layout rules that matter

- **Power loop:** each half-bridge has its high FET, low FET and shunt in a
  tight line, and two of the 100 V MLCCs straddle the leg from V_BUS to GND
  (shunt end) within ~2 mm. The return runs on L2 directly underneath. Target
  loop inductance < 2 nH per leg.
- **Gate drive:** DRV8353 GHx/SHx and GLx/SPx run as close pairs to each FET
  (SHx is the gate return). Fit 0 Ω gate-resistor footprints (0402) so
  IDRIVE and resistors can be tuned without a respin. Add RC snubber
  footprints across each low FET, not fitted.
- **Shunts:** Kelvin traces from the shunt pads to SNx/SPx, routed as a pair
  away from the switch nodes, with an RC filter footprint at the DRV.
- **Analog:** the CSA outputs, VREF and the V_BUS divider route over solid L2,
  away from phase nodes. VDDA/VREF+ get a ferrite and their own 1 µF + 10 nF.
- **Thermal:** an array of 0.3 mm vias under each FET drain tab into the
  L3/L4 pours. The bottom copper is the heat-spreader interface: keep the
  area under the FETs free of components and exposed (mask opening) for the
  optional plate with a thermal pad.
- **Clearance:** solder-masked outer conductors up to 100 V need 0.13 mm
  (IPC-2221B B4); use **0.2 mm for V_BUS and phase nets** and 0.6 mm where
  copper is exposed (pads, test points). This is encoded as custom DRC
  rules ([06](06-kicad-as-code.md)).
- **Encoder:** the MT6835 sits exactly on the board centre (the shaft axis),
  bottom side, with no copper pours under the sensor area on any layer and no
  high-current paths within ~5 mm (stray fields).
- **Current capacity:** 15 A continuous in 2 oz outer + 1 oz inner pours
  needs ~4–5 mm effective width per net in two layers at a 20 °C rise
  (IPC-2152). Motor pads and the XT30 land on pours, not traces.
- **Assembly:** two-sided, with the bottom holding the MT6835 and its
  passives only. Paste windows on the QFN and FET thermal pads (~50–60 %
  coverage). Fiducials on both sides. All parts at least 0.5 mm from the
  board edge, and the V-cut/tab rail added by JLC (panel by JLC).

### JLC capabilities to confirm at order time

- 4-layer, 1.6 mm, 2 oz outer / 1 oz inner, ENIG
- Via-in-pad with epoxy fill and cap (for the FET and QFN thermal vias), and
  whether it is free on multilayer boards
- Minimum annular ring and trace/space for 2 oz outer copper
- Two-sided standard assembly; through-hole soldering for the XT30PW
- Current Extended-part loading fee and private-library stock reservation
  (MT6835, DRV8353RS)
