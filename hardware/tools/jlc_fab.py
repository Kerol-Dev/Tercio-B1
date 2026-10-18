#!/usr/bin/env python3
"""JLCPCB fabrication and assembly files from the routed board. Run with KiCad's Python after layout.py:

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 hardware/tools/jlc_fab.py

Writes hardware/build/jlc/:
  tercio-b1-gerbers.zip   copper ×6, mask, paste, silk, outline + Excellon drill (PTH / NPTH), exactly
                          JLC's KiCad 9 settings (X2 + netlist attributes on, absolute coordinates);
                          only gerbers and the two drill files (no maps, no job file)
  tercio-b1-bom.csv       Comment, Designator, Footprint, LCSC — fitted parts only (no DNP, no pads);
                          every designator listed (JLC does not expand ranges like R404-R406)
  tercio-b1-cpl.csv       Designator, Mid X, Mid Y, Layer, Rotation — same origin as the gerbers
  ORDER.md                the order-form settings and the parts to confirm in JLC's placement preview

Both tables come from the board itself, so they always agree with each other and with the gerbers.

CPL conventions (the ones JLC and the two common KiCad plugins use):
  - Mid X / Mid Y: centre of the part's pads (JLC places its library footprint by its centre), mm,
    Y up, absolute — the same coordinates as the gerbers (KiCad page origin, Y negated).
  - Rotation: top = KiCad angle + c; bottom = 180 − KiCad angle + c ("as seen from above the part"),
    where c corrects the zero orientation of KiCad's footprint against JLC's library footprint.
  - c by footprint family from the community table maintained with the Fabrication Toolkit plugin
    (github.com/bennymeg/Fabrication-Toolkit, plugins/transformations.csv); the same formula is in
    Bouni's kicad-jlcpcb-tools. Families without an entry get c = 0 and are listed for checking.
"""
from __future__ import annotations

import collections
import csv
import pathlib
import re
import shutil
import subprocess
import zipfile

import pcbnew

HERE = pathlib.Path(__file__).resolve().parent.parent
PCB = HERE / "kicad" / "tercio-b1.kicad_pcb"
OUT = HERE / "build" / "jlc"
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
NAME = "tercio-b1"
LAYERS = ("F.Cu,In1.Cu,In2.Cu,In3.Cu,In4.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts")

# zero-orientation corrections (degrees) by KiCad footprint name: community table (see above)
CORRECTIONS = [
    (r"^CP_Elec_", 180), (r"^JST_GH_SM", 180), (r"^LQFP-", 270), (r"^SOIC-", 270), (r"^SOT-23", 180),
    (r"^TDSON-8-1", 270), (r"^TSSOP-", 270), (r"^USON-10", 270), (r"^QFN-", 90),
]
# polarized or multi-pin parts whose family has no table entry: check these in JLC's preview
CHECK = [r"^D_", r"^LED_", r"VQFN", r"XT30", r"^Crystal_"]


def correction(fpname):
    for rx, c in CORRECTIONS:
        if re.search(rx, fpname):
            return c, True
    return 0, False


def field(fp, name):
    for f in fp.GetFields():
        if f.GetName() == name:
            return f.GetText().strip()
    return ""


def natural(ref):
    m = re.match(r"([A-Za-z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def compress(refs):
    """R404,R405,R406 → R404-R406, for ORDER.md only: JLC's BOM parser takes "R404-R406" as one
    designator (and then reports R404–R406 missing from the BOM), so the BOM lists every ref."""
    refs = sorted(refs, key=natural)
    out, run = [], []
    for r in refs + [None]:
        if r and run and natural(r)[0] == natural(run[-1])[0] and natural(r)[1] == natural(run[-1])[1] + 1:
            run.append(r)
            continue
        if run:
            out.append(run[0] if len(run) < 3 else f"{run[0]}-{run[-1]}")
            if len(run) == 2:
                out.append(run[1])
        run = [r] if r else []
    return ",".join(out)


def main():
    board = pcbnew.LoadBoard(str(PCB))
    ox, oy = 0.0, 0.0                    # absolute, like the gerbers and drill files (JLC's KiCad guide)
    if OUT.exists():
        shutil.rmtree(OUT)
    gdir = OUT / "gerbers"
    gdir.mkdir(parents=True)

    # ---- gerbers + drill, JLC's KiCad 9 guide: Protel extensions, X2 and netlist attributes on (their parser
    # identifies the layers and the profile from them), 4.6 mm, absolute origin; Excellon mm, decimal,
    # alternate oval mode, PTH and NPTH separate. The zip holds only the gerbers and the two drill files.
    subprocess.run([KICAD_CLI, "pcb", "export", "gerbers", "-o", str(gdir), "-l", LAYERS, "--precision", "6",
                    "--check-zones", str(PCB)], check=True, capture_output=True)
    subprocess.run([KICAD_CLI, "pcb", "export", "drill", "-o", str(gdir) + "/", "--format", "excellon",
                    "--drill-origin", "absolute", "--excellon-zeros-format", "decimal", "--excellon-oval-format",
                    "alternate", "--excellon-units", "mm", "--excellon-separate-th", str(PCB)],
                   check=True, capture_output=True)
    files = sorted(p for p in gdir.iterdir() if p.is_file() and p.suffix.lower() != ".gbrjob")
    with zipfile.ZipFile(OUT / f"{NAME}-gerbers.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.name)

    # ---- BOM + CPL -------------------------------------------------------------------------------------
    groups = collections.defaultdict(list)
    cpl, missing, check = [], [], []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        attrs = fp.GetAttributes()
        if fp.IsDNP() or attrs & pcbnew.FP_EXCLUDE_FROM_BOM:
            continue
        lcsc = field(fp, "LCSC")
        if not lcsc:
            missing.append(ref)
            continue
        fpname = str(fp.GetFPID().GetLibItemName())
        groups[(fp.GetValue(), fpname, lcsc)].append(ref)
        if attrs & pcbnew.FP_EXCLUDE_FROM_POS_FILES:
            continue
        ext = None                       # pad extents, numerically (BOX2I.Merge through SWIG is unreliable)
        for pad in fp.Pads():
            b = pad.GetBoundingBox()
            e = (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())
            ext = e if ext is None else (min(ext[0], e[0]), min(ext[1], e[1]), max(ext[2], e[2]), max(ext[3], e[3]))
        if ext is None:
            cx, cy = pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)
        else:
            cx, cy = pcbnew.ToMM((ext[0] + ext[2]) / 2), pcbnew.ToMM((ext[1] + ext[3]) / 2)
        x, y = cx - ox, oy - cy
        theta = fp.GetOrientationDegrees()
        corr, known = correction(fpname)
        bottom = fp.IsFlipped()
        rot = ((180.0 - theta) if bottom else theta) + corr
        rot = round(rot % 360.0, 2)
        cpl.append({"Designator": ref, "Mid X": f"{x:.4f}mm", "Mid Y": f"{y:.4f}mm",
                    "Layer": "Bottom" if bottom else "Top", "Rotation": f"{rot:g}"})
        if not known and any(re.search(rx, fpname) for rx in CHECK):
            check.append((ref, fp.GetValue(), fpname, "Bottom" if bottom else "Top", rot))

    with (OUT / f"{NAME}-bom.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC"])
        for (value, fpname, lcsc), refs in sorted(groups.items(), key=lambda kv: natural(sorted(kv[1], key=natural)[0])):
            w.writerow([value, ",".join(sorted(refs, key=natural)), fpname, lcsc])
    cpl.sort(key=lambda r: natural(r["Designator"]))
    with (OUT / f"{NAME}-cpl.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writeheader()
        w.writerows(cpl)

    top = sum(r["Layer"] == "Top" for r in cpl)
    lines = [
        "# Tercio B1 rev A — JLCPCB order",
        "",
        "Upload `tercio-b1-gerbers.zip`, then for assembly `tercio-b1-bom.csv` and `tercio-b1-cpl.csv`.",
        "",
        "## PCB",
        "",
        "| Setting | Value |",
        "|---|---|",
        "| Layers | 6 |",
        "| Dimensions | 46 × 46 mm |",
        "| Thickness | 1.6 mm |",
        "| Outer / inner copper | 2 oz / 1 oz (0.5 oz inner is fine electrically if 1 oz is not offered) |",
        "| Stackup | JLC's standard 6-layer 1.6 mm (no impedance control needed) |",
        "| Surface finish | ENIG, 1 µ\" gold |",
        "| Material | FR4 TG155 (JLC selects it automatically with 0.2 mm vias) |",
        "| Solder mask / silkscreen | Matte black / white |",
        "| Via covering | Epoxy filled & capped (JLC's default on 6 layers; the board has vias in pads) |",
        "| Min via hole / diameter | 0.2 / 0.45 mm → option 0.2mm/(0.3/0.35mm); JLC adds the 4-wire Kelvin test |",
        "| Min track / space | 0.15 / 0.15 mm (JLC's minimum for 2 oz outer copper) |",
        "| Mark on PCB | Remove Mark |",
        "| Silkscreen technology | High-precision printing (labels down to 0.8 mm cap height: strokes of "
        "0.15–0.16 mm, at ink-jet printing's limit) |",
        "| Confirm production file | Yes (rev A: review JLC's processed files before production) |",
        "",
        "## Assembly",
        "",
        f"Both sides: {top} parts on top, {len(cpl) - top} on the bottom. "
        f"{len(groups)} BOM lines; the XT30 (J101) is through-hole.",
        "",
        "Gerbers: X2 + netlist attributes, absolute coordinates, Protel extensions (In1–In4 → .g1–.g4),",
        "PTH and NPTH drill files separate — JLC's KiCad 9 settings. The CPL uses the same coordinates.",
        "",
        "In JLC's placement preview, check pin 1 / polarity of the parts below (their footprint family has",
        "no entry in the community rotation table, so the CPL uses KiCad's zero orientation as is):",
        "",
        "| Ref | Value | Footprint | Side | CPL rotation |",
        "|---|---|---|---|---|",
    ]
    for ref, value, fpname, side, rot in sorted(check, key=lambda t: natural(t[0])):
        lines.append(f"| {ref} | {value} | {fpname} | {side} | {rot:g} |")
    if missing:
        lines += ["", f"Not assembled (no LCSC code): {compress(missing)}"]
    (OUT / "ORDER.md").write_text("\n".join(lines) + "\n")
    print(f"gerbers: {len(files)} files → {OUT / (NAME + '-gerbers.zip')}")
    print(f"BOM: {len(groups)} lines; CPL: {len(cpl)} parts ({top} top, {len(cpl) - top} bottom)")
    print(f"check in JLC's preview: {', '.join(r for r, *_ in check) or 'none'}")
    if missing:
        print(f"no LCSC code (not assembled): {compress(missing)}")


if __name__ == "__main__":
    main()
