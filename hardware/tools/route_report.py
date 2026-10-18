#!/usr/bin/env python3
"""Routing review: per-net length / vias / layers for the critical classes, and per-layer copper plots.

Run with KiCad's Python after layout.py:

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 hardware/tools/route_report.py

Writes build/route-report.txt and build/copper/<plot>.svg(.png).
"""
import collections
import pathlib
import subprocess

import pcbnew

HERE = pathlib.Path(__file__).resolve().parent.parent
PCB = HERE / "kicad" / "tercio-b1.kicad_pcb"
BDIR = HERE / "build"
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
CRITICAL = ("Power", "Supply", "Gate", "Kelvin")


def main():
    b = pcbnew.LoadBoard(str(PCB))
    per = collections.defaultdict(lambda: {"len": 0.0, "vias": 0, "layers": collections.Counter(), "width": set()})
    for t in b.GetTracks():
        n = t.GetNetname()
        if t.Type() == pcbnew.PCB_VIA_T:
            per[n]["vias"] += 1
        else:
            ln = pcbnew.ToMM(t.GetLength())
            per[n]["len"] += ln
            per[n]["layers"][b.GetLayerName(t.GetLayer())] += ln
            per[n]["width"].add(round(pcbnew.ToMM(t.GetWidth()), 2))
    lines = []
    tot_len = sum(v["len"] for v in per.values())
    tot_vias = sum(v["vias"] for v in per.values())
    lines.append(f"tracks {tot_len:.0f} mm, vias {tot_vias}")
    by_layer = collections.Counter()
    for v in per.values():
        by_layer.update(v["layers"])
    lines.append("by layer: " + ", ".join(f"{k} {v:.0f} mm" for k, v in sorted(by_layer.items())))
    for cls in CRITICAL:
        lines.append(f"\n[{cls}]")
        for net in sorted(per):
            ni = b.FindNet(net)
            if not ni or ni.GetNetClassName() != cls:
                continue
            v = per[net]
            lay = " ".join(f"{k}:{x:.1f}" for k, x in sorted(v["layers"].items()))
            lines.append(f"  {net:40s} {v['len']:6.1f} mm  vias {v['vias']:2d}  w {sorted(v['width'])}  {lay}")
    text = "\n".join(lines)
    (BDIR / "route-report.txt").write_text(text + "\n")
    print(text)
    plots = {"top": "F.Cu", "in1": "In1.Cu", "in2": "In2.Cu", "in3": "In3.Cu", "in4": "In4.Cu", "bottom": "B.Cu",
             "signal": "F.Cu,In2.Cu,In3.Cu,B.Cu"}
    out = BDIR / "copper"
    out.mkdir(exist_ok=True)
    for name, layers in plots.items():
        svg = out / f"{name}.svg"
        subprocess.run([KICAD_CLI, "pcb", "export", "svg", "--mode-single", "-l", f"{layers},Edge.Cuts",
                        "--page-size-mode", "2", "--exclude-drawing-sheet", "--drill-shape-opt", "1",
                        *(["--mirror"] if name == "bottom" else []), "-o", str(svg), str(PCB)], capture_output=True)
        # Quick Look rasterises SVG (no extra tools needed on macOS): writes <name>.svg.png
        subprocess.run(["qlmanage", "-t", "-s", "1800", "-o", str(out), str(svg)], capture_output=True)


if __name__ == "__main__":
    main()
