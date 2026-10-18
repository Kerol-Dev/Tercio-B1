# 9. Risks and schedule

## 9.1 Launch guardrails (B1 work starts now, alongside the 1 Dec launch)

You chose to start the schematic now. These rules keep that from touching the
S1/FD launch:

1. **No B1 change touches the S1, FD, IMU, web or docs repos before 1 Dec.**
   Shared code is *copied* into Tercio-B1; `tercio-common` is extracted
   after launch.
2. **Launch work always preempts B1 work.** If a launch task slips, B1 pauses,
   not the other way round.
3. **Freeze B1 from 23 Nov to 7 Dec** (launch week plus the first week of
   orders and support). Only reading and thinking during the freeze.
4. **Small purchases only before launch** (the ESC1 dev board, breakouts,
   magnets). No PCB order before mid-December.
5. **Time cap:** your call (a number of evenings per week). Write it down, so
   the B1 schedule below is planned against it rather than against launch
   time.

**S1 and the 1M/5M bus (resolved 2026-10-12):** no S1 units are built yet,
so the firmware that ships on them is still open. The bus-profile parameter
(7.5) goes into the S1 shipping firmware as part of the normal S1 work, at
Kerol's discretion. Guardrail 1 is about B1 work, not about S1 features.

## 9.2 Risk register

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| 1 | B1 work erodes launch time (decided parallel start) | M | H | Guardrails 9.1; freeze 23 Nov – 7 Dec; time cap |
| 2 | Solo bandwidth after launch (support, orders, bugs) eats the Dec–Jan B1 window | H | M | Plan says "order rev A ~21 Dec" but tolerates a 2–4 week slip; nothing customer-facing depends on B1 dates |
| 3 | First power stage rings, overshoots or kills FETs at 48–52 V | M | H | Hand-specified loop geometry with checked loop area; 80 V FETs; 0 Ω gate-R and snubber footprints; DRV IDRIVE tuning; staged voltage steps; 10 boards per spin so failures are affordable |
| 4 | 15 A uncooled is not reached | M | M | Rate from measurement (method fixed in advance); FET upgrade path (BSC026); heat-spreader option; marketing leads with what's measured |
| 5 | 80 A peak limited by thermal mass, VDS OCP or shunt pulse rating | M | L | Locked-rotor pulse tests; publish current *and* duration; 5 W metal-strip shunt alternate |
| 6 | Current-sense noise from the DRV CSAs at high dv/dt | M | M | Kelvin routing, RC filter footprints, valley sampling, gain per profile; INA240 fallback footprint is not planned on rev A, so a CSA problem means rev B |
| 7 | Part stock: MT6835 (1,462, JLC-only), DRV8353RS (1,675), BM08B (1,233), G474CBT6 (481) | M | H | Reserve pilot quantities in JLC's private library before rev C; MT6826S check for a pin-compatible fallback; G431 is the base |
| 8 | KiCad-as-code (code owns everything) costs more time than hand layout, or Freerouting cannot finish the dense board | M | M | Framework timeboxed (2–3 weeks); explicit code routes for critical nets; generator reused for later boards. If it slips badly, revisit the decision (your call, not mine) |
| 9 | KiCad drops the SWIG `pcbnew` API | L (for B1) | M | One adapter module; KiCad 10.0.6 pinned for the B1 programme |
| 10 | 1M/5M profile: switching every node on a mixed bus is risky (a node left at the old rate goes silent) | M | M | Two-phase switch with automatic fallback to 500k/2.5M if no traffic is seen within N seconds; the profile ships in the S1/FD firmware from the start |
| 11 | FOC firmware takes longer than planned (calibration, ID, robustness) | H | M | Host simulator first (F0), ESC1 dev board before rev A (F1), reuse of S1 structure; release scope fixed in [01](01-requirements.md) §1.6 |
| 12 | Regen or bench accidents destroy boards during tests | M | M | E-load CV clamp, battery for braking tests, firmware regen limit from day one, current-limited supply in every stage |
| 13 | JLC two-sided assembly / QFN voiding on the DRV and FET pads | L | M | Paste window design, X-ray on rev A if offered, inspect one board destructively |
| 14 | Competitor response (mjbots cuts n1 price or ships a cheaper 46 mm board) | M | M | Lead with the ecosystem (stepper + BLDC + IMU on one bus, browser panel), which a price cut doesn't erase |
| 15 | Compliance (CE/UKCA/FCC for an electronic module sold to end users) | M | M | Same approach as the S1 (check what was decided there); pre-scan EMC on rev B if possible |
| 16 | Chinese New Year (6 Feb 2027) stops JLC for ~2 weeks | H | L | Rev B ordered after the holiday; use the gap for firmware and tests on rev A |

L = likelihood, I = impact (H/M/L).

## 9.3 Schedule (realistic, solo, 2–3 spins)

Dates assume the guardrails above and part-time work until launch.

| When | Phase | Output | Spend |
|---|---|---|---|
| 12 Oct – 22 Nov 2026 | **Pre-launch, part-time.** Generator framework (6.8); B1 circuit blocks in code; ERC clean; firmware F0 (FOC core + simulator + tests); order ESC1 + MT6835 breakouts + magnets | Schematic ~80 %, sim green | ~$60 |
| 23 Nov – 7 Dec | **Freeze** (launch) | — | — |
| 8 – 21 Dec | Finish schematic; power-stage geometry; Freerouting; DRC + parity + checks; review packet; JLC quote; **order rev A** (10 boards) | Rev A ordered ~21 Dec | ~$450–550 |
| 22 Dec – ~11 Jan 2027 | Fab + holiday shipping. Firmware F1 on the ESC1 (FOC on a real motor) | FOC proven on a dev board | — |
| ~11 Jan – 5 Feb | **Rev A bring-up**, stages 0–8; F2/F3 on own hardware; rev B change list | Rev A characterised at ≤ 52 V | — |
| 6 – ~18 Feb | CNY: JLC closed. Thermal, peak, regen and fault tests (stages 9–12) on rev A; F4 (protocol, libraries, panel) | Measured ratings (preliminary) | — |
| ~22 Feb | **Order rev B** (10 boards): fixes + heat-spreader interface + cost-downs | | ~$450–500 |
| ~10 Mar – 10 Apr | Rev B validation: stages 8–14, 1M/5M mixed bus with S1/FD, CAN bootloader, 24 h soak; ratings final | Release candidate firmware (F5) | heat spreader samples ~$50 |
| ~20 Apr | **Order rev C = pilot run** (100 boards) if rev B needed only minor fixes; otherwise rev C is a third 10-board spin and the pilot moves ~6 weeks later | | ~$2,550 + fixture ~$150 |
| May 2027 | Production test fixture, 10–20 beta users, docs and site, starter bundle | | cables/packaging ~$200 |
| **June 2027** | **Launch Tercio B1** (later, ~July/Aug, if a third engineering spin is needed) | | |

**Spin budget:** rev A ~$500, rev B ~$500, pilot ~$2,700–2,900, plus
~$300–500 in tools and accessories. That is **~$4,000–4,500** to launch, or
~$4,500–5,000 if a third engineering spin is needed.

## 9.4 What would move the date

- **Earlier:** rev A works well enough that rev B is the pilot (2 spins). The
  KiCad generator lands faster than 2–3 weeks.
- **Later:** a power-stage redesign after rev A (most likely cause), a
  current-sensing problem forcing external amplifiers, part stock-outs,
  post-launch support load.
