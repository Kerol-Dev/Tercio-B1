# 3. Part shortlist (live LCSC / JLCPCB data)

**Data taken 2026-10-12** by [`tools/parts_lookup.py`](../tools/parts_lookup.py)
from the JLCPCB parts search (assembly stock, Basic/Extended, JLC price) and
the LCSC product API (LCSC store stock). There are 686 rows in
`data/parts-live-2026-10-12*.csv`. Prices are USD per unit at 10 and 100
pieces, with no tax or shipping. Stock moves daily, so **re-run the script
before every order**:

```bash
cd ~/Documents/Projects/Tercio-B1 && python3 -I tools/parts_lookup.py && python3 -I tools/parts_lookup.py tools/candidates-extra.txt
```

"JLC stock" is what JLCPCB can place on an assembled board today. "LCSC stock"
is the separate retail store (a part can be JLC-only, e.g. the MT6835). Almost
everything here is an **Extended** part: JLC charges a per-unique-part loading
fee for those on every assembly order (historically $3; check the current
fee). Clones sold under the original part number with a suffix (`-VB`, `-JSM`,
`(TOKMAS)`, `(ES)`) were left out on purpose. Do not use them in the power
stage without qualifying them yourself.

✅ = decided with Kerol · ★ = recommended, Kerol's call · ◇ = alternate

## 3.1 MCU

| | MPN | LCSC | Package | JLC stock | LCSC stock | $ @10 | $ @100 |
|---|---|---|---|---:|---:|---:|---:|
| ✅ | STM32G431CBT6 | C529355 | LQFP-48 | 5241 | 4197 | 4.38 | 4.05 |
| ◇ | STM32G474CBT6 | C730123 | LQFP-48 | 481 | 164 | 3.78 | 3.51 |
| | STM32G431CBU6 | C529356 | UFQFPN-48 | 3561 | 2575 | 7.01 | 5.86 |
| | STM32G474CET6 | C730125 | LQFP-48 | **0** | **0** | 20.47 | 15.88 |
| | STM32G474CEU6 | C1235412 | UFQFPN-48 | 6 | 0 | 13.08 | 10.91 |
| | STM32G491CET6 | C3227300 | LQFP-48 | 3 | 0 | 8.40 | 8.13 |
| | STM32G431RBT6 | C431633 | LQFP-64 | 3117 | 2980 | 5.13 | 4.30 |
| | STM32G474RET6 | C521608 | LQFP-64 | 353 | 139 | 11.93 | 10.16 |

**Why the G431:** it is the same chip, PlatformIO variant and board file as
the S1 and IMU, so `CanBus`, `FlashStore`, `Clock` and the build config carry
over with zero porting. It has three op-amps, two ADCs, CORDIC and FMAC. The
G474's advantages are three more ADCs (all three phases sampled at once),
128 KB RAM and FDCAN2/3, and none of them is needed with the DRV8353's
amplifiers. The 512 KB parts that would have allowed A/B firmware updates are
out of stock or 4× the price, so the plan uses a small CAN bootloader on the
G431 instead ([07](07-firmware.md) §7.9). The G474CBT6 is pin-compatible, and
the pin map ([04](04-architecture.md)) uses only peripherals both chips have.

## 3.2 Gate driver

| | MPN | LCSC | Package | JLC stock | LCSC stock | $ @10 | $ @100 | Notes |
|---|---|---|---|---:|---:|---:|---:|---|
| ✅ | DRV8353RSRGZR | C506246 | VQFN-48 7×7 | 1675 | 1580 | 5.23 | 4.61 | 9–100 V, SPI, 3 CSAs (gain 5/10/20/40), LM5008A buck (6–95 V in, 350 mA), VDS OCP, 6x/3x/1x PWM |
| | DRV8323RSRGZR | C545497 | VQFN-48 | **0** | **0** | 5.56 | 5.39 | Would have been the 60 V choice; out of stock |
| | DRV8323RHRGZR | C543035 | VQFN-48 | 754 | 732 | 2.72 | 2.12 | 60 V, resistor-configured (no SPI) |
| | DRV8323SRTAR | C701784 | WQFN-40 | 158 | 158 | 3.50 | 2.77 | 60 V, SPI, no buck |
| | DRV8353SRTAR | C701785 | WQFN-40 | 72 | 0 | 3.97 | 3.44 | 100 V, SPI, no buck; low stock |
| | 6EDL7141XUMA1 | C3655737 | VQFN-48 | 263 | 263 | 4.00 | 3.01 | Infineon 60 V, SPI, 3 CSAs, buck + LDOs |
| | DRV8301DCAR | C98969 | HTSSOP-56 | 7034 | 7034 | 2.93 | 2.20 | Old ODrive v3 part: 60 V, 2 CSAs, 1.5 A buck, large |
| | MP6539GV-Z | C5676243 | QFN-28 | 1022 | — | 3.15 | 2.65 | 100 V, no CSA, no SPI |
| | STDRIVE101 | C2969847 | VFQFPN-24 | 357 | 111 | 1.80 | 1.36 | 75 V, 600 mA drive, no CSA |
| | FD6288Q / FD6288T | C328453 / C97683 | QFN-24 / TSSOP-20 | 0 | 0 | 1.88 / 0.73 | 1.33 / 0.54 | 20 V-VCC bootstrap driver; out of stock at JLC |
| | EG2133 | C190343 | TSSOP-20 | 0 | 3996 | 0.43 | 0.32 | Bootstrap driver; LCSC only, so you would need to consign it |

**Why the DRV8353RS:** the DRV8323RS is out of stock everywhere. The
DRV8353RS is the in-stock part that keeps SPI, the amplifiers *and* the buck,
and its 100 V rating is what makes 52 V operation with hot-plug margin
reasonable. The FD6288/EG2133 route ($0.30–0.50) would save ~$4 but adds a
separate buck, external or op-amp current sensing and comparator-based
overcurrent protection. It also loses VDS monitoring, which is the only thing
that catches a phase-to-ground short (that current bypasses low-side shunts).
For a solo developer's first power stage, the protection is worth $4.

## 3.3 MOSFETs (6 per board)

| | MPN | LCSC | Package | V / Rds(on) | JLC stock | $ @10 | $ @100 |
|---|---|---|---|---|---:|---:|---:|
| ★ | BSC030N08NS5 | C501507 | SuperSO8 5×6 | 80 V / 3.0 mΩ, Qg 76 nC | 24529 | 0.77 | 0.57 |
| ◇ | BSC026N08NS5ATMA1 | C5955453 | SuperSO8 5×6 | 80 V / 2.6 mΩ | 5379 | 1.27 | 0.96 |
| ◇ | BSC040N08NS5 | C534333 | SuperSO8 5×6 | 80 V / 4.0 mΩ, Qg 43 nC | 6574 | 1.09 | 0.81 |
| | TPH4R008NH,L1Q | C141587 | SOP-Advance 5×6 | 80 V / 4.0 mΩ | 4792 | 0.86 | 0.64 |
| | CSD19502Q5B | C2864118 | SON 5×6 | 80 V / 3.4 mΩ | 7508 | 1.37 | 1.13 |
| | CSD19532Q5B | C473333 | SON 5×6 | 100 V / 4.6 mΩ | 2410 | 1.83 | 1.35 |
| | BSC070N10NS5 | C534364 | SuperSO8 5×6 | 100 V / 7 mΩ | 25994 | 0.50 | 0.33 |
| | BSC014N06NS | C113391 | SuperSO8 5×6 | 60 V / 1.45 mΩ | 29960 | 1.20 | 0.84 |
| | NTMFS5C628NL | C145537 | SO-8FL | 60 V / 2.4 mΩ | 7957 | 0.62 | 0.46 |
| | IPT012N08N5 | C531199 | TOLL | 80 V / 1.2 mΩ | 5825 | 2.38 | 1.89 |
| | SiR680ADP | C3289502 | PowerPAK SO-8 | 80 V / 3.5 mΩ | 999 | 6.33 | 5.12 |

80 V parts, because 52 V operation plus ringing and regen needs ~1.5×
headroom. The BSC030N08NS5 has the deepest stock and lowest price at 3 mΩ. At
15 A RMS, conduction loss is ~0.3–0.5 W per FET when hot, which is the main
input to the thermal rating. If the bench shows conduction-limited heating,
the BSC026 is a footprint-compatible upgrade; if switching-limited, the
lower-charge BSC040. **TOLL was rejected:** six 10 × 11.7 mm packages do not
fit 46 × 46 mm next to everything else, and 1.2 mΩ is overkill at 15 A
continuous. It is the right package for a later "X"-class board.

## 3.4 Current sensing

| | MPN | LCSC | Package | JLC stock | $ @10 | $ @100 | Notes |
|---|---|---|---|---:|---:|---:|---|
| ★ | RLP25FEGR001 | C459678 | 2512 | 27351 | 0.089 | 0.071 | 1 mΩ 3 W ±1 % 50 ppm/K |
| ◇ | YLR12-2-1F-W | C469371 | 2512 | 45428 | 0.101 | 0.080 | 1 mΩ 2 W |
| ◇ | ASR-M-3-1F | C469427 | 2512 | 42042 | 0.273 | 0.216 | 1 mΩ 5 W, metal strip |
| | RLP25FEGR002 | C459679 | 2512 | 49666 | 0.073 | 0.059 | 2 mΩ (only if peak drops to 40 A) |
| fallback | INA240A2PWR | C129949 | TSSOP-8 | 9082 | 1.89 | 1.38 | PWM-rejection amp, if the DRV CSAs disappoint |
| | INA181A2IDBVR | C2058784 | SOT-23-6 | 21061 | 0.335 | 0.268 | Cheap low-side amp |
| | TP181A1-CR | C2902349 | SC-70-6 | 9550 | 0.316 | 0.243 | |
| | INA199A1DCKR | C59135 | SC-70-6 | 98868 | 0.326 | 0.244 | 14 kHz bandwidth: too slow for FOC |

Plan: 1 mΩ low-side shunts into the DRV8353's three amplifiers, with the gain
chosen per motor profile over SPI:

| Gain | Full scale (±, VREF = 3.3 V, ~0.25 V headroom) | ADC step |
|---|---|---|
| 40 (gimbal) | ±35 A | 20 mA |
| 20 | ±70 A | 40 mA |
| 10 (QDD, 80 A peaks) | ±140 A | 81 mA |

Shunt loss is 0.23 W at 15 A RMS and 6.4 W during an 80 A burst (inside a
3 W 2512's short-pulse rating; confirm the pulse curve). The G474's internal
programmable-gain op-amps would allow the same gain switching without the DRV,
which is a reason to keep the G474 as the alternate.

## 3.5 Encoders

| | MPN | LCSC | Package | Bits | JLC stock | LCSC stock | $ @10 | $ @100 |
|---|---|---|---|---|---:|---:|---:|---:|
| ✅ | MT6835GT-STD-R | C2932578 | TSSOP-16 | 21 (AMR, SPI ≤ 16 MHz) | 1462 | 0 | 4.29 | 3.54 |
| ◇ | MT6826SGT-STD-R | C27636731 | TSSOP-16 | 15 | 4822 | 4822 | 3.20 | 2.39 |
| | MT6701CT-STD-R | C3003196 | SOP-8 | 14 (SSI/I2C/ABZ) | 4442 | 4442 | 1.56 | 1.29 |
| | TLE5012BE1000 | C123083 | SO-8 | 15 (SSC) | 11599 | 11223 | 3.64 | 2.68 |
| | MA600AGQE | C49240579 | QFN-16 | 16 | 1161 | — | 4.78 | 4.11 |
| | MA732GQ-Z | C3824836 | QFN-16 | 14 | 559 | — | 4.77 | 4.18 |
| | AS5047P-ATST (moteus) | C55112284 | TSSOP-14 | 14 | **44** | 44 | 3.78 | 3.05 |
| | AS5047U-HTSM | C2153630 | SSOP-14 | 14 | 288 | 288 | 5.38 | 4.36 |
| | AS5048A-HTSP | C2655181 | TSSOP-14 | 14 | 104 | 104 | 5.82 | 4.79 |

The MT6835 is a JLC-only part today (0 on the LCSC store). Before rev C,
reserve stock for the pilot run (JLC private parts library). The MT6826S is
the same vendor and package. Check whether its pinout matches the MT6835; if
it does, one footprint serves as a stock-out fallback. Confirm the MT6835's
SPI frame and CRC in the official NOVOSENSE/MagnTek datasheet: distributor
summaries give 21-bit, SPI up to 16 MHz, 3.3–5 V, ABZ/UVW/PWM outputs and
2–10 µs latency, but none describes the CRC.

## 3.6 CAN-FD

| | MPN | LCSC | Package | Rate | JLC stock | $ @10 | $ @100 |
|---|---|---|---|---|---:|---:|---:|
| ★ | MCP2562FDT-E/SN | C511335 | SOIC-8 | 8 Mbit/s, VIO pin | 5333 | 1.44 | 1.12 |
| ◇ | TJA1462AT/0Z | C3234095 | SOIC-8 | 8 Mbit/s, signal-improvement class | 10844 | 0.83 | 0.62 |
| | TJA1051T/3/1J | C38695 | SOIC-8 | 5 Mbit/s, VIO | 278027 | 0.48 | 0.36 |
| | SIT1044QT/3 | C5121967 | SOP-8 | 5 Mbit/s, VIO | 9856 | 0.42 | 0.32 |
| | TCAN1042VDRQ1 | C485806 | SOIC-8 | 5 Mbit/s | 926 | 0.58 | 0.44 |
| ★ ESD | PESD2CAN | C2687131 | SOT-23 | | 658668 | 0.036 | 0.036 |
| | NUP2105LT1G | C14486 | SOT-23 | | 252177 | 0.083 | 0.068 |

The MCP2562FD is the FD adapter's transceiver, so the whole family shares one
part and its loop-delay characterisation (the S1's TDC setting). It is
specified to 8 Mbit/s, so the 1M/5M profile has headroom. If ringing at
5 Mbit/s on longer daisy chains is a problem, the TJA1462 is the drop-in to
try: it is the cheaper part and designed to damp ringing. Check which suffix
has the VIO pin needed for 3.3 V logic.

## 3.7 Power, protection and bulk capacitance

| | MPN | LCSC | Package | JLC stock | $ @10 | $ @100 | Notes |
|---|---|---|---|---:|---:|---:|---|
| ★ | (DRV8353R buck) | — | — | — | — | — | 5 V from V_BUS. No separate buck on rev A |
| fallback | LMR38010SDDAR | C5219310 | SO PowerPAD-8 | 309 | 0.74 | 0.52 | 80 V 1 A buck, if the 350 mA budget breaks |
| fallback | SCT2A10STER | C509053 | ESOP-8 | 4928 | 1.33 | 1.00 | 85 V 0.6 A |
| | MP9486AGN-Z | C404013 | SOIC-8-EP | 1973 | 2.95 | 2.44 | 100 V 1 A |
| | LMR16006XDDCR | C87080 | SOT-6 | 33737 | 0.48 | 0.36 | 60 V only: too low for a 52 V board |
| ★ | TLV75533PDBVR | C404027 | SOT-23-5 | 132914 | 0.14 | 0.11 | 3.3 V LDO from 5 V |
| ◇ | TPS7A2033PDBVR | C2862740 | SOT-23-5 | 186366 | 0.22 | 0.17 | Low-noise LDO, if a separate analog rail helps |
| ★ | SMBJ54A | C2891330 | SMB | 6025 | 0.043 | 0.043 | 54 V standoff, 60 V breakdown |
| ◇ | SMCJ58A | C357975 | SMC | 5996 | 0.12 | 0.10 | 1.5 kW. Higher standoff, so higher clamp |
| ★ | FS32X475K101EGG | C381466 | 1210 | 160984 | 0.23 | 0.19 | 4.7 µF 100 V X7R, ×10 |
| ◇ | HMK325C7475KN-TE | C697607 | 1210 | 127003 | 0.36 | 0.28 | Taiyo Yuden X7S |
| | CC1206KKX7R0BB225 | C577211 | 1206 | 1060578 | 0.18 | 0.13 | 2.2 µF 100 V |
| ★ | VZH470M1KTR-1010 | C249920 | 10×10 SMD | 7438 | 0.22 | 0.18 | 47 µF 80 V electrolytic, for damping. Height decision |
| ◇ | JVJ80V100M10x10 | C46550424 | 10×10.5 SMD | 35809 | 0.17 | 0.13 | 100 µF 80 V |
| ◇ | MA80V100M10X12 | C53120969 | 10×12.5 SMD | 6506 | 0.38 | 0.28 | 100 µF 80 V, 30 mΩ (low-ESR); taller |

Bulk capacitance: 10 × 4.7 µF 100 V MLCCs lose ~60 % of their capacitance at
48 V DC bias, so ~20 µF effective. That is enough for ripple current spread
across ten parts. It is not enough to damp a long supply cable, hence one
electrolytic for damping. It costs height (10 mm). The alternative is "no
electrolytic on board, put one on the XT30 pigtail", which mjbots also leaves
to the user. Decide at layout.

TVS: no TVS can clamp a full-energy surge below 80 V while standing off
52 V. The SMBJ54A handles hot-plug ringing and short spikes. Regen is
handled by firmware (regen-current limit + OV fault) and, on the bench, by an
electronic load in CV mode ([08](08-bringup.md)). Recommend users fit an
anti-spark connector (XT90-S) on the battery side.

## 3.8 Sensing, connectors and the rest

| | MPN | LCSC | Package | JLC stock | $ @10 | $ @100 | Notes |
|---|---|---|---|---:|---:|---:|---|
| ★ | NCP18XH103F03RB | C13564 | 0603 | 178011 | 0.046 | 0.039 | FET NTC 10 k B3434 |
| ✅ | X322516MLB4SI | C13738 | 3225 | 152708 | 0.093 | 0.074 | 16 MHz, **Basic**, same as S1/FD |
| ✅ | XT30PW-M30.G.Y | C431092 | THT right angle | 72882 | 0.33 | 0.26 | Power in |
| ◇ | XT30UPB-M | C428721 | THT vertical | 68489 | 0.26 | 0.25 | If the edge layout prefers vertical |
| ✅ | SM04B-GHS-TB(LF)(SN) | C189895 | GH-4 right angle | 26931 | 0.30 | 0.27 | CAN in/out ×2 (right angle, decided at layout) |
| ✅ | SH-SM08B-GHS-TB(LF)(SN) (Shou Han) | C42376901 | GH-compatible 8P right angle | 30593 | 0.08 | 0.07 | Aux. Genuine JST SM08B-GHS-TB had 0 JLC stock on 2026-10-12; same footprint, so the genuine part drops in if JLC stocks it |
| ◇ | BM08B-GHS-TBT(LF)(SN) | C133062 | GH-8 top entry | 1233 | 0.37 | 0.30 | Vertical alternative (not used) |
| ★ | TPD4E05U06DQAR | C138714 | USON-10 | 102774 | 0.084 | 0.067 | Aux ESD ×2 |
| ✅ | KT-0603R and a green 0603 | C2286 / Basic | 0603 | 7.1 M | 0.008 | 0.008 | LEDs |
| — | B-G431B-ESC1 | not on LCSC | — | — | ~$20 | — | Firmware dev board; buy from ST, Mouser or DigiKey |
| — | Diametric magnet 6 × 2.5 mm N35+ | not on LCSC | — | — | — | — | Kit item; the magnet holder depends on the motor |

## 3.9 KiCad libraries from LCSC parts

`easyeda2kicad` is not installed yet. With `uv`, which is installed:

```bash
uv tool install easyeda2kicad
```

```bash
easyeda2kicad --full --lcsc_id=C506246 --output ~/Documents/Projects/Tercio-B1/hardware/lib/tercio-b1
```

`--full` writes the symbol, the footprint and the 3D model. Rules for using its output:

- **Prefer KiCad's own library** where it has the part: `MCU_ST_STM32G4:STM32G431CBTx`, standard
  QFN/TSSOP/SOT footprints, `Connector_JST` GH footprints. Use easyeda2kicad output
  for the rest (DRV8353RS symbol, MT6835, SuperSO8 FETs, XT30PW).
- **Check every imported footprint against the datasheet** before the first order:
  pin 1, exposed-pad paste windows (DRV8353 and FET thermal pads: split the paste into
  a ~50–60 % window grid to avoid floating), and courtyard.
- The generator ([06](06-kicad-as-code.md)) records the LCSC code as a symbol field,
  so the JLC BOM and CPL come straight from the design.
