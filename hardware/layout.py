#!/usr/bin/env python3
"""Generate the Tercio B1 board. Run with KiCad's Python (it needs pcbnew):

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 hardware/layout.py

Reads build/tercio-b1.net (run build.py first), writes kicad/tercio-b1.kicad_pcb,
then runs DRC and renders the board.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from gen import pcb as P  # noqa: E402
from gen import sexpr  # noqa: E402
from gen.sexpr import Sym, find  # noqa: E402
from b1 import art, board, copper  # noqa: E402

KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
KDIR, BDIR = HERE / "kicad", HERE / "build"
PCB = KDIR / "tercio-b1.kicad_pcb"


def stackup(path: pathlib.Path):
    """Matte black solder mask, white silk, ENIG, 1.6 mm 6-layer (2 oz outer / 1 oz inner)."""
    tree = sexpr.loads(path.read_text())
    setup = find(tree, "setup")

    def lay(name, typ, **kw):
        item = [Sym("layer"), name, [Sym("type"), typ]]
        for k, v in kw.items():
            item.append([Sym(k), v])
        return item

    st = [Sym("stackup"),
          lay("F.SilkS", "Top Silk Screen", color="White"),
          lay("F.Paste", "Top Solder Paste"),
          lay("F.Mask", "Top Solder Mask", color="Black", thickness=0.01),
          lay("F.Cu", "copper", thickness=0.07),
          lay("dielectric 1", "prepreg", color="FR4 natural", thickness=0.2, material="FR4", epsilon_r=4.4, loss_tangent=0.02),
          lay("In1.Cu", "copper", thickness=0.035),
          lay("dielectric 2", "core", color="FR4 natural", thickness=0.3, material="FR4", epsilon_r=4.6, loss_tangent=0.02),
          lay("In2.Cu", "copper", thickness=0.035),
          lay("dielectric 3", "prepreg", color="FR4 natural", thickness=0.3, material="FR4", epsilon_r=4.4, loss_tangent=0.02),
          lay("In3.Cu", "copper", thickness=0.035),
          lay("dielectric 4", "core", color="FR4 natural", thickness=0.3, material="FR4", epsilon_r=4.6, loss_tangent=0.02),
          lay("In4.Cu", "copper", thickness=0.035),
          lay("dielectric 5", "prepreg", color="FR4 natural", thickness=0.2, material="FR4", epsilon_r=4.4, loss_tangent=0.02),
          lay("B.Cu", "copper", thickness=0.07),
          lay("B.Mask", "Bottom Solder Mask", color="Black", thickness=0.01),
          lay("B.Paste", "Bottom Solder Paste"),
          lay("B.SilkS", "Bottom Silk Screen", color="White"),
          [Sym("copper_finish"), "ENIG"], [Sym("dielectric_constraints"), Sym("no")]]
    for i, item in enumerate(setup):
        if isinstance(item, list) and item and item[0] == "stackup":
            setup[i] = st
            break
    else:
        setup.insert(1, st)
    text = sexpr.dumps(tree) + "\n"
    # the XT30PW-M has no model in KiCad 10's library: use the one built by tools/xt30pw_model.py
    text = text.replace("${KICAD10_3DMODEL_DIR}/Connector_AMASS.3dshapes/AMASS_XT30PW-M_1x02_P2.50mm_Horizontal.step",
                        "${KIPRJMOD}/lib/3d/AMASS_XT30PW-M.step")
    path.write_text(text)


def project_rules():
    """Board rules and net classes in the project file (JLC 6-layer capabilities, conservative)."""
    pro_path = KDIR / "tercio-b1.kicad_pro"
    pro = json.loads(pro_path.read_text())
    pro["board"] = {"design_settings": {"rules": {
        "min_clearance": 0.127, "min_track_width": 0.127, "min_via_diameter": 0.45, "min_through_hole_diameter": 0.2,
        "min_via_annular_width": 0.1, "min_copper_edge_clearance": 0.3, "min_hole_to_hole": 0.25,
        "min_hole_clearance": 0.2, "min_silk_clearance": 0.0, "min_text_height": 0.6, "min_text_thickness": 0.1},
        # pre-defined sizes for routing by hand (0 = "use net class"): neck down into 0.5 mm pins with 0.2
        "track_widths": [0.0, 0.15, 0.2, 0.25, 0.3, 0.4, 0.8],
        "via_dimensions": [{"diameter": 0.0, "drill": 0.0}, {"diameter": 0.45, "drill": 0.2}, {"diameter": 0.5, "drill": 0.25},
                           {"diameter": 0.6, "drill": 0.3}]}}
    def nc(name, clearance, width, via, drill, priority):
        # every field set: a class with gaps becomes a composite with Default ("Power,Default"),
        # which the Specctra exporter does not recognise, and the router would see one class only
        return {"name": name, "priority": priority, "clearance": clearance, "track_width": width,
                "via_diameter": via, "via_drill": drill, "microvia_diameter": 0.3, "microvia_drill": 0.1,
                "diff_pair_width": 0.2, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
                "wire_width": 6, "bus_width": 12, "line_style": 0, "tuning_profile": "",
                "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"}

    pro["net_settings"] = {"classes": [
        nc("Default", 0.15, 0.15, 0.45, 0.2, 2147483647),  # logic: 0.15 / 0.15; 0.45 / 0.2 vias (filled in pads)
        nc("Power", 0.2, 0.4, 0.7, 0.35, 0),      # the current runs in the pours; routed V_BUS / phase feeds are small
        nc("Supply", 0.2, 0.3, 0.6, 0.3, 1),     # tens of mA (VM/VDRAIN) to ~0.4 A peak (buck SW): 0.3 mm in 2 oz
        nc("Gate", 0.2, 0.2, 0.5, 0.25, 2),       # 0.2 mm keeps 60 V (GHx rides on the phase) well apart
        nc("Kelvin", 0.15, 0.15, 0.45, 0.2, 3)],
        "netclass_patterns": [
            {"netclass": "Power", "pattern": p} for p in ("VBUS", "*PHASE_*", "*LSRC_*")]
        + [{"netclass": "Supply", "pattern": p} for p in ("*VM_F", "*VDRAIN", "*/SW", "*BUCK_L", "+5V")]
        + [{"netclass": "Gate", "pattern": p} for p in ("GH?", "GL?", "Net-(Q30?-G)")]
        + [{"netclass": "Kelvin", "pattern": p} for p in ("SP_?", "SN_?")]}
    pro.setdefault("meta", {})["version"] = 3
    pro_path.write_text(json.dumps(pro, indent=2) + "\n")


ROUTES = HERE / "b1" / "routes.json"   # every track and via (router + hand): re-applied on each regeneration


def save_routes():
    """Store the board's tracks, arcs and vias in b1/routes.json (after routing by hand in KiCad)."""
    import pcbnew
    b = pcbnew.LoadBoard(str(PCB))
    xy = lambda v: [round(pcbnew.ToMM(v.x) - 150, 4), round(pcbnew.ToMM(v.y) - 100, 4)]  # noqa: E731
    out = {"tracks": [], "arcs": [], "vias": []}
    for t in b.GetTracks():
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_VIA_T:
            out["vias"].append({"net": net, "at": xy(t.GetPosition()), "size": round(pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)), 4),
                                "drill": round(pcbnew.ToMM(t.GetDrillValue()), 4)})
        elif t.Type() == pcbnew.PCB_ARC_T:
            out["arcs"].append({"net": net, "layer": b.GetLayerName(t.GetLayer()), "start": xy(t.GetStart()),
                                "mid": xy(t.GetMid()), "end": xy(t.GetEnd()), "width": round(pcbnew.ToMM(t.GetWidth()), 4)})
        else:
            out["tracks"].append({"net": net, "layer": b.GetLayerName(t.GetLayer()), "start": xy(t.GetStart()),
                                  "end": xy(t.GetEnd()), "width": round(pcbnew.ToMM(t.GetWidth()), 4)})
    for k in out:
        out[k].sort(key=lambda d: json.dumps(d, sort_keys=True))
    ROUTES.write_text(json.dumps(out, indent=1) + "\n")
    print(f"saved {len(out['tracks'])} tracks, {len(out['arcs'])} arcs, {len(out['vias'])} vias → {ROUTES}")


def add_routes(board_, data):
    """Put tracks / arcs / vias (layout-frame mm, by net name) on the board, locked; returns how many."""
    import pcbnew
    V = lambda p: pcbnew.VECTOR2I(pcbnew.FromMM(p[0] + 150), pcbnew.FromMM(p[1] + 100))  # noqa: E731
    n = 0
    for d in data.get("tracks", []):
        t = pcbnew.PCB_TRACK(board_)
        t.SetStart(V(d["start"])); t.SetEnd(V(d["end"])); t.SetWidth(pcbnew.FromMM(d["width"]))
        t.SetLayer(board_.GetLayerID(d["layer"])); t.SetNet(board_.FindNet(d["net"])); t.SetLocked(True)
        board_.Add(t); n += 1
    for d in data.get("arcs", []):
        a = pcbnew.PCB_ARC(board_)
        a.SetStart(V(d["start"])); a.SetMid(V(d["mid"])); a.SetEnd(V(d["end"])); a.SetWidth(pcbnew.FromMM(d["width"]))
        a.SetLayer(board_.GetLayerID(d["layer"])); a.SetNet(board_.FindNet(d["net"])); a.SetLocked(True)
        board_.Add(a); n += 1
    have = {(t.GetPosition().x, t.GetPosition().y) for t in board_.GetTracks() if t.Type() == pcbnew.PCB_VIA_T}
    for d in data.get("vias", []):
        if (V(d["at"]).x, V(d["at"]).y) in have:
            continue                      # b1/copper.py's own vias are already there
        v = pcbnew.PCB_VIA(board_)
        v.SetPosition(V(d["at"])); v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetWidth(pcbnew.FromMM(d["size"])); v.SetDrill(pcbnew.FromMM(d["drill"]))
        v.SetNet(board_.FindNet(d["net"])); v.SetLocked(True)
        board_.Add(v); n += 1
        have.add((V(d["at"]).x, V(d["at"]).y))
    return n


def apply_routes(board_):
    """Put the stored routes (b1/routes.json) back on a freshly placed board."""
    return add_routes(board_, json.loads(ROUTES.read_text())) if ROUTES.exists() else 0


FAST_PY = pathlib.Path(os.environ.get(
    "TERCIO_FAST_PY", pathlib.Path.home() / "Documents/Projects/Tercio-s1/Hardware/CAD/NEMA23-Adapter/.venv/bin/python"))


def route():
    """Route the board: export the problem (gen/route_export.py), solve it with the compiled
    negotiated-congestion router (gen/fastroute.py, a Python with Numba), put the result on the
    board, pour GND and fill."""
    import time

    import pcbnew
    from b1 import routing
    from gen import route_export
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f} s] {m}", flush=True)  # noqa: E731
    board_ = pcbnew.LoadBoard(str(PCB))
    ns = json.loads((KDIR / "tercio-b1.kicad_pro").read_text())["net_settings"]
    rdir = BDIR / "route"
    rdir.mkdir(parents=True, exist_ok=True)
    npz, pj, out = rdir / "problem.npz", rdir / "problem.json", rdir / "routes-out.json"
    # the negotiating router does not need the staggered DRV escapes (they forced fan-out order on the old
    # one-net-at-a-time router and would only act as walls here): plain 0.5 mm escapes everywhere
    route_export.export(board_, ns["classes"], ns.get("netclass_patterns") or [], routing.units, npz, pj,
                        holes=board.HOLES, escape={}, log=log)   # vias may run under silk: filled and capped
    if os.environ.get("FASTROUTE_RESULT"):    # a solve already made from this same problem (e.g. offline)
        out = pathlib.Path(os.environ["FASTROUTE_RESULT"])
        log(f"using the solve in {out}")
    else:
        log("solving (gen/fastroute.py)…")
        r = subprocess.run([str(FAST_PY), str(HERE / "gen" / "fastroute.py"), str(npz), str(pj), str(out)])
        if r.returncode or not out.exists():
            raise SystemExit("fastroute failed")
    data = json.loads(out.read_text())
    n = add_routes(board_, data)
    while True:                          # a path end that stopped one grid step past its target: drop it
        board_.BuildConnectivity()
        conn = board_.GetConnectivity()
        dead = [t for t in board_.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and conn.TestTrackEndpointDangling(t, False)]
        if not dead:
            break
        for t in dead:
            board_.Remove(t)
        n -= len(dead)
        log(f"removed {len(dead)} dangling track stub(s)")
    (BDIR / "route-failures.txt").write_text("\n".join(map(str, data.get("failed", []))) + "\n")
    w = P.Pcb.wrap(board_)
    copper.pours(w)
    w.fill_zones()
    pcbnew.SaveBoard(str(PCB), board_)
    stackup(PCB)
    project_rules()          # SaveBoard rewrites the .kicad_pro with KiCad's defaults (no net classes)
    log(f"routing: {n} tracks/vias placed, contested cells {data.get('contested')}, failed {data.get('failed')}")


def main():
    if "--save-routes" in sys.argv:
        save_routes()
        return
    if "--route-only" in sys.argv:          # route the board as placed (placement unchanged)
        route()
        render()
        return
    p = P.Pcb(BDIR / "tercio-b1.net", KDIR / "lib" / "Tercio_B1.pretty", layers=6)
    p.outline(radius=3.0)
    ds = p.board.GetDesignSettings()            # drill/place origin at the bottom-left corner: the gerbers
    ds.SetAuxOrigin(p.V(-23.0, 23.0))           # and the JLC placement file (tools/jlc_fab.py) share it
    ds.SetGridOrigin(p.V(-23.0, 23.0))
    board.place(p)
    art.draw(p)
    copper.build(p)
    kept = apply_routes(p.board)
    if kept:
        print(f"routes.json: {kept} tracks/vias re-applied (the router only adds what is missing)")
    for fp in p.board.GetFootprints():  # minimalist silk: references live on the fab layer only
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
    p.fill_zones()
    p.save(PCB)
    stackup(PCB)
    project_rules()
    print(f"placed {len(p.fps)} footprints → {PCB}" + (f"; {len(p.failed)} failed: {p.failed}" if p.failed else ""))
    if "--no-route" not in sys.argv:
        route()
    render()


def render():
    BDIR.mkdir(exist_ok=True)
    for side in ("top", "bottom"):
        subprocess.run([KICAD_CLI, "pcb", "render", "--side", side, "--width", "1600", "--height", "1600",
                        "--quality", "high", "--use-board-stackup-colors", "--zoom", "1.0",
                        "-o", str(BDIR / f"render-{side}.png"), str(PCB)], capture_output=True)


if __name__ == "__main__":
    main()
