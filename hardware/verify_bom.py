#!/usr/bin/env python3
"""Export the JLC BOM from the generated schematic and check every LCSC code live.

    python3 hardware/verify_bom.py [--boards 10]

Writes hardware/build/bom-jlc.csv (Comment, Designator, Footprint, LCSC) and prints
each LCSC line with JLC stock, Basic/Extended and the catalogue description, so a
wrong code (value or package mismatch) stands out. Exits non-zero when a part is
missing or short of stock for the requested build.
"""
from __future__ import annotations

import csv
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
SEARCH = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


def jlc(code: str):
    body = json.dumps({"keyword": code, "currentPage": 1, "pageSize": 5}).encode()
    req = urllib.request.Request(SEARCH, data=body, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            rows = json.load(urllib.request.urlopen(req, timeout=30))["data"]["componentPageInfo"]["list"] or []
            return next((r for r in rows if r["componentCode"] == code), None)
        except Exception:
            time.sleep(2 + 2 * attempt)
    return None


def main():
    boards = int(sys.argv[sys.argv.index("--boards") + 1]) if "--boards" in sys.argv else 10
    out = HERE / "build"
    out.mkdir(exist_ok=True)
    raw = out / "bom-raw.csv"
    subprocess.run([KICAD_CLI, "sch", "export", "bom", "--fields", "Reference,Value,Footprint,LCSC,MPN,${DNP},${QUANTITY}",
                    "--labels", "Ref,Value,Footprint,LCSC,MPN,DNP,Qty", "--group-by", "LCSC,Value,Footprint,DNP",
                    "--exclude-dnp", "-o", str(raw), str(HERE / "kicad" / "tercio-b1.kicad_sch")],
                   check=True, capture_output=True)
    rows = list(csv.DictReader(raw.open()))
    jlc_rows, problems, extended = [], 0, 0
    cost = {10: 0.0, 100: 0.0}
    print(f"{'LCSC':10} {'Qty':>3} {'Lib':8} {'Stock':>8}  {'Value':18} Catalogue")
    for r in rows:
        code = r["LCSC"].strip()
        qty = int(r["Qty"])
        if not code:
            print(f"{'—':10} {qty:>3} {'':8} {'':>8}  {r['Value'][:18]:18} no LCSC code ({r['Ref']})")
            continue
        info = jlc(code)
        time.sleep(0.3)
        if not info:
            print(f"{code:10} {qty:>3} {'?':8} {'?':>8}  {r['Value'][:18]:18} NOT FOUND")
            problems += 1
            continue
        lib = "Basic" if info["componentLibraryType"] == "base" else "Extended"
        for n in cost:
            breaks = sorted(info.get("componentPrices") or [], key=lambda b: b["startNumber"])
            unit = next((b["productPrice"] for b in reversed(breaks) if b["startNumber"] <= qty * n), breaks[0]["productPrice"] if breaks else 0)
            cost[n] += unit * qty
        extended += lib == "Extended"
        stock = info["stockCount"] or 0
        flag = "" if stock >= qty * boards * 2 else "  << LOW STOCK"
        problems += bool(flag)
        print(f"{code:10} {qty:>3} {lib:8} {stock:>8}  {r['Value'][:18]:18} {info['componentModelEn']} · "
              f"{info['componentSpecificationEn']} · {(info.get('describe') or '')[:60]}{flag}")
        jlc_rows.append({"Comment": r["Value"], "Designator": r["Ref"], "Footprint": r["Footprint"].split(":")[-1],
                         "LCSC": code})
    with (out / "bom-jlc.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Comment", "Designator", "Footprint", "LCSC"])
        w.writeheader()
        w.writerows(jlc_rows)
    print(f"\n{len(jlc_rows)} BOM lines, {extended} Extended (loading fee each), {problems} problems → {out / 'bom-jlc.csv'}")
    print(f"component cost per board (JLC prices today): ${cost[10]:.2f} at 10 boards, ${cost[100]:.2f} at 100 boards")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
