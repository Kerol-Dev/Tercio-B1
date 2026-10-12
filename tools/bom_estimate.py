#!/usr/bin/env python3
"""BOM cost estimate for Tercio B1 rev A at 10 and 100 boards.

Prices for parts with an LCSC code come from the live lookup CSVs in data/
(JLCPCB assembly price breaks, USD). Lines marked "est" are lumped passives
whose unit prices are typical JLC Basic prices, not looked up. PCB and
assembly fees are assumptions to confirm with a JLC quote (the quote API needs
a login). Run after tools/parts_lookup.py:

    python3 tools/bom_estimate.py
"""
import csv
import glob
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (refs, description, LCSC code or None, qty per board, est unit price @10, est @100)
BOM = [
    ("U1", "MCU STM32G431CBT6 (LQFP-48)", "C529355", 1, None, None),
    ("U2", "Gate driver DRV8353RSRGZR (buck + 3 CSA + SPI)", "C506246", 1, None, None),
    ("U3", "Encoder MT6835GT-STD-R (21-bit, SPI)", "C2932578", 1, None, None),
    ("U4", "CAN-FD transceiver MCP2562FDT-E/SN", "C511335", 1, None, None),
    ("U5", "LDO 3.3 V TLV75533PDBVR", "C404027", 1, None, None),
    ("Q1-Q6", "MOSFET BSC030N08NS5 80 V 3 mOhm 5x6", "C501507", 6, None, None),
    ("R1-R3", "Shunt 1 mOhm 2512 3 W RLP25FEGR001", "C459678", 3, None, None),
    ("C1-C10", "Bulk MLCC 4.7 uF 100 V X7R 1210", "C381466", 10, None, None),
    ("C11", "Bulk electrolytic 47 uF 80 V 10x10 (height check)", "C249920", 1, None, None),
    ("D1", "TVS SMBJ54A", "C2891330", 1, None, None),
    ("Y1", "Crystal 16 MHz 3225 (Basic, same as S1/FD)", "C13738", 1, None, None),
    ("RT1", "NTC 10k 0603 (FET temperature)", "C13564", 1, None, None),
    ("D2", "CAN ESD PESD2CAN", "C2687131", 1, None, None),
    ("D3,D4", "Aux ESD TPD4E05U06DQAR", "C138714", 2, None, None),
    ("J1", "XT30PW-M power (right angle)", "C431092", 1, None, None),
    ("J2,J3", "JST-GH 4-pin SM04B-GHS-TB (CAN in/out)", "C189895", 2, None, None),
    ("J4", "JST-GH 8-pin BM08B-GHS-TBT (aux)", "C133062", 1, None, None),
    ("LED1,LED2", "LED 0603 (Basic)", "C2286", 2, None, None),
    ("-", "Driver buck passives: inductor, 100 V Schottky, caps, FB divider", None, 1, 0.30, 0.22),
    ("-", "Driver support caps (100 V CP caps, VGLS/DVDD/VCP, VM HF bypass)", None, 1, 0.10, 0.07),
    ("-", "Logic passives: ~50x 0402 R/C, CAN split termination, dividers, filters", None, 1, 0.18, 0.12),
    ("-", "Leg HF decoupling 100 nF 100 V 0603 x6", None, 1, 0.05, 0.03),
]

# Fixed costs per order and per-board fabrication (assumptions, USD).
PCB_PER_BOARD = {10: 5.00, 100: 1.60}  # 4-layer 46x46, 2 oz outer / 1 oz inner, ENIG
ASSEMBLY_FIXED = {10: 25 * 2 + 3 * 18 + 4, 100: 25 * 2 + 3 * 18 + 4}  # 2-sided setup, ~18 Extended part fees, THT setup
ASSEMBLY_PER_BOARD = {10: 1.20, 100: 0.90}  # joints, THT XT30, handling
SHIPPING = {10: 35.0, 100: 90.0}  # DHL/FedEx estimate to the EU; duties not included


def load_prices():
    prices = {}
    for path in sorted(glob.glob(str(ROOT / "data" / "parts-live-*.csv"))):
        for r in csv.DictReader(open(path)):
            if r.get("status") == "ok" and r.get("lcsc"):
                prices[r["lcsc"]] = r
    return prices


def unit_price(row, total_qty):
    p1, p10, p100 = (float(row[k]) for k in ("jlc_p1", "jlc_p10", "jlc_p100"))
    return p100 if total_qty >= 100 else p10 if total_qty >= 10 else p1


def main():
    prices = load_prices()
    out_rows = []
    totals = {10: 0.0, 100: 0.0}
    for refs, desc, code, qty, est10, est100 in BOM:
        line = {"refs": refs, "description": desc, "lcsc": code or "", "qty": qty}
        for n in (10, 100):
            if code:
                row = prices[code]
                u = unit_price(row, qty * n)
                line["stock"] = row["jlc_stock"]
                line["library"] = row["library"]
            else:
                u = est10 if n == 10 else est100
                line["stock"] = "est"
                line["library"] = "Basic (est)"
            line[f"unit@{n}"] = round(u, 4)
            line[f"board@{n}"] = round(u * qty, 3)
            totals[n] += u * qty
        out_rows.append(line)

    out = ROOT / "data" / "bom-estimate.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["refs", "description", "lcsc", "library", "stock", "qty",
                                          "unit@10", "board@10", "unit@100", "board@100"])
        w.writeheader()
        w.writerows(out_rows)

    print("| Refs | Part | LCSC | Library | JLC stock | Qty | $/board @10 | $/board @100 |")
    print("|---|---|---|---|---:|---:|---:|---:|")
    for r in out_rows:
        print(f"| {r['refs']} | {r['description']} | {r['lcsc'] or '—'} | {r['library']} | {r['stock']} | {r['qty']} | "
              f"{r['board@10']:.2f} | {r['board@100']:.2f} |")
    print(f"| | **Components** | | | | | **{totals[10]:.2f}** | **{totals[100]:.2f}** |")
    print()
    print("| Per board | 10 boards | 100 boards |")
    print("|---|---:|---:|")
    rows = [
        ("Components", totals[10], totals[100]),
        ("PCB (4-layer, 2 oz outer)", PCB_PER_BOARD[10], PCB_PER_BOARD[100]),
        ("Assembly, fixed fees spread", ASSEMBLY_FIXED[10] / 10, ASSEMBLY_FIXED[100] / 100),
        ("Assembly, per board", ASSEMBLY_PER_BOARD[10], ASSEMBLY_PER_BOARD[100]),
        ("Shipping (no duties)", SHIPPING[10] / 10, SHIPPING[100] / 100),
    ]
    for name, a, b in rows:
        print(f"| {name} | {a:.2f} | {b:.2f} |")
    t10 = sum(r[1] for r in rows)
    t100 = sum(r[2] for r in rows)
    print(f"| **Landed cost per board** | **{t10:.2f}** | **{t100:.2f}** |")
    print(f"| Order total | {t10 * 10:.0f} | {t100 * 100:.0f} |")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
