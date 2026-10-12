#!/usr/bin/env python3
"""Live LCSC / JLCPCB stock and price lookup for the Tercio BLDC shortlist.

Reads tools/candidates.txt (or the file given as the first argument) and
writes data/parts-live-<date>[-<file stem>].csv plus a
markdown table on stdout. Standard library only; re-run it before ordering.

candidates.txt, one candidate per line ('#' starts a comment):

    group | query | how
      group  shortlist section (MCU, Gate driver, ...)
      query  an exact manufacturer part number, or a keyword search
      how    "mpn" (default): keep rows whose model starts with the query
             "kw:N": keyword search, keep the N rows with the most JLC stock
             "kw:N:base": the same, Basic library parts only

Sources:
  JLCPCB parts search  (assembly stock, Basic/Extended/Preferred, JLC price)
  LCSC product detail  (LCSC store stock and price breaks)
Prices are USD as returned for an anonymous visitor (no tax, no shipping).
"""
import csv
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.request

JLC_SEARCH = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
LCSC_DETAIL = "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={}"
UA = {"User-Agent": "Mozilla/5.0 (tercio-bldc parts_lookup)", "Content-Type": "application/json"}
ROOT = pathlib.Path(__file__).resolve().parent.parent


def http_json(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=UA, method="POST" if data else "GET")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # network hiccup or rate limit: back off and retry
            if attempt == 2:
                print(f"  ! {url[:60]}: {e}", file=sys.stderr)
                return None
            time.sleep(2 + 3 * attempt)


def jlc_search(keyword, size=30, basic_only=False):
    body = {"keyword": keyword, "currentPage": 1, "pageSize": size}
    if basic_only:
        body["componentLibraryType"] = "base"
    d = http_json(JLC_SEARCH, body)
    try:
        return d["data"]["componentPageInfo"]["list"] or []
    except (TypeError, KeyError):
        return []


def price_at(breaks, qty, lo="startNumber", hi="endNumber", val="productPrice"):
    """Unit price for `qty` from a list of price breaks."""
    best = None
    for b in sorted(breaks or [], key=lambda b: b[lo]):
        if b[lo] <= qty:
            best = b[val]
    if best is None and breaks:
        best = sorted(breaks, key=lambda b: b[lo])[0][val]
    return float(best) if best is not None else None


def lcsc_detail(code):
    d = http_json(LCSC_DETAIL.format(code))
    r = (d or {}).get("result")
    if not isinstance(r, dict):  # not sold on lcsc.com (JLC-only or delisted)
        return None, None, None
    breaks = [{"startNumber": p["ladder"], "productPrice": p["usdPrice"]} for p in r.get("productPriceList") or []]
    return r.get("stockNumber"), price_at(breaks, 10), price_at(breaks, 100)


def library(row):
    if row.get("componentLibraryType") == "base":
        return "Basic"
    return "Extended (preferred)" if row.get("preferredComponentFlag") else "Extended"


def main():
    today = dt.date.today().isoformat()
    src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tools" / "candidates.txt"
    lines = src.read_text().splitlines()
    out_rows = []
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        group, query = parts[0], parts[1]
        how = parts[2] if len(parts) > 2 and parts[2] else "mpn"
        print(f"{group}: {query}", file=sys.stderr)
        if how.startswith("kw"):
            bits = how.split(":")
            n = int(bits[1]) if len(bits) > 1 else 3
            rows = jlc_search(query, size=40, basic_only=len(bits) > 2 and bits[2] == "base")
            rows = sorted(rows, key=lambda r: -(r.get("stockCount") or 0))[:n]
        else:
            rows = [r for r in jlc_search(query) if (r.get("componentModelEn") or "").upper().startswith(query.upper())]
            if not rows:
                out_rows.append({"group": group, "query": query, "mpn": query, "lcsc": "", "status": "not found on JLCPCB/LCSC"})
                continue
        for r in rows:
            code = r["componentCode"]
            l_stock, l_p10, l_p100 = lcsc_detail(code)
            time.sleep(0.4)
            out_rows.append({
                "group": group,
                "query": query,
                "mpn": r.get("componentModelEn"),
                "brand": r.get("componentBrandEn"),
                "lcsc": code,
                "package": r.get("componentSpecificationEn"),
                "library": library(r),
                "jlc_stock": r.get("stockCount"),
                "jlc_p1": price_at(r.get("componentPrices"), 1),
                "jlc_p10": price_at(r.get("componentPrices"), 10),
                "jlc_p100": price_at(r.get("componentPrices"), 100),
                "lcsc_stock": l_stock,
                "lcsc_p10": l_p10,
                "lcsc_p100": l_p100,
                "describe": (r.get("describe") or "")[:160],
                "status": "ok",
            })
        time.sleep(0.4)

    fields = ["group", "query", "mpn", "brand", "lcsc", "package", "library", "jlc_stock",
              "jlc_p1", "jlc_p10", "jlc_p100", "lcsc_stock", "lcsc_p10", "lcsc_p100", "describe", "status"]
    suffix = "" if len(sys.argv) < 2 else "-" + src.stem
    out = ROOT / "data" / f"parts-live-{today}{suffix}.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in out_rows:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"wrote {out} ({len(out_rows)} rows)", file=sys.stderr)

    fmt = lambda v: "" if v in (None, "") else (f"{v:.3f}" if isinstance(v, float) and v < 1 else f"{v:.2f}" if isinstance(v, float) else str(v))
    print("| Group | MPN | LCSC | Package | Library | JLC stock | JLC $@10 | JLC $@100 | LCSC stock |")
    print("|---|---|---|---|---|---:|---:|---:|---:|")
    for r in out_rows:
        if r["status"] != "ok":
            print(f"| {r['group']} | {r['query']} | — | — | **{r['status']}** | | | | |")
            continue
        print(f"| {r['group']} | {r['mpn']} | {r['lcsc']} | {r['package']} | {r['library']} | {fmt(r['jlc_stock'])} | "
              f"{fmt(r['jlc_p10'])} | {fmt(r['jlc_p100'])} | {fmt(r['lcsc_stock'])} |")


if __name__ == "__main__":
    main()
