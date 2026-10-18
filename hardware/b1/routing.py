"""Tercio B1 rev A — routing plan. `units()` is the plan gen/fastroute.py solves (tiers below); `plan()`
drives the first, slower router in gen/router.py and is kept for reference.

1. Kelvin pairs: SPx, then SNx drawn to it (pair strength 2: leaving SP's side costs double), so the
   shunt voltage travels as a tight pair.
2. Gate loops, per leg: GHx, then the SHx return from the DRV's SHx pin to the high-side sources
   beside it (small loop area), then the resistor → gate hop; GLx and its hop.
3. The buck's input loop (VIN pin 43 → its 1 µF), then the DRV supply and buck nets.
4. A via to the In1 plane next to every GND pad that is not already in a GND pour.
5. +3V3 (0.25 mm), +3.3VA, the V_BUS feeds; then everything else, shortest first.
Tiers 1–3 are "critical": the router never lets the rest push them out.
"""
from .board import FETS

HS_SOURCES = ("1", "2", "3")
DRV_SH = {"A": "9", "B": "16", "C": "19"}
GATE_R = {"A": ("R301", "R302"), "B": ("R305", "R306"), "C": ("R309", "R310")}
SUPPLY = ("/Gate driver and buck/VM_F", "/Gate driver and buck/VDRAIN", "/Gate driver and buck/VCP",
          "/Gate driver and buck/CPH", "/Gate driver and buck/CPL", "/Gate driver and buck/VGLS",
          "/Gate driver and buck/SW", "/Gate driver and buck/BST", "/Gate driver and buck/VCC_BUCK",
          "/Gate driver and buck/BUCK_L", "/Gate driver and buck/DVDD", "+5V")
GATE_W = 0.2

# Staggered escape corridors on the DRV (mm beyond the pad), the classic fan-out: the pin nearest the
# turn turns first, so every track has room to spread before it needs a via. Left side, pins 8–12
# (phase A) turn down; bottom side, phase B (13–17) is a staircase to the left, the SO outputs and
# phase C (24…18) a staircase to the right.
STEP = 0.8   # > the 45° clearance band of a 0.25 mm track (0.69 mm), so each turn clears the next pin
ESCAPE = {("U201", str(pin)): 0.5 + i * STEP for i, pin in enumerate((12, 11, 10, 9, 8))}      # phase A, down
ESCAPE |= {("U201", str(pin)): 0.5 + i * STEP for i, pin in enumerate((13, 14, 15, 16, 17))}   # phase B, left
ESCAPE |= {("U201", str(pin)): 0.5 + i * STEP for i, pin in enumerate((24, 23, 22, 21, 20, 19, 18))}  # SO, C
# top side (buck and logic): 48…44 staircase to the left, VIN (43) above them to the VIN cap, SW (42)
# straight up into the diode's cathode, DVDD (40) up under the diode body, INx (39…37) to the right
ESCAPE |= {("U201", str(pin)): 0.5 + i * 0.5 for i, pin in enumerate((48, 47, 46, 45, 44))}
ESCAPE |= {("U201", "43"): 3.1, ("U201", "42"): 3.77, ("U201", "41"): 0.5, ("U201", "40"): 3.1}
ESCAPE |= {("U201", str(pin)): 0.5 + i * STEP for i, pin in enumerate((37, 38, 39))}


def plan(r, log=print, stages=5):
    done = set()

    def net(name):
        done.add(name)
        return r.code[name]

    # 1. Kelvin pairs (first: shunt C sits between legs B and C, so its pair needs the inner lane)
    for ph in "ABC":
        r.route_net(net(f"SP_{ph}"), name=f"SP_{ph}")
        r.route_net(net(f"SN_{ph}"), name=f"SN_{ph}", attract=f"SP_{ph}")
    r.drain()
    log(f"routing: Kelvin pairs done ({len(r.routes)} routes)")

    # 2. gate loops
    for ph in "ABC":
        hs, ls = FETS[ph]
        rh, rl = GATE_R[ph]
        r.route_net(net(f"GH{ph}"), width=GATE_W, name=f"GH{ph}")
        r.connect_pads(r.code[f"PHASE_{ph}"], [("U201", DRV_SH[ph])], [(hs, n) for n in HS_SOURCES],
                       width=GATE_W, name=f"SH{ph}", attract=f"GH{ph}")
        r.route_net(net(f"Net-({hs}-G)"), width=GATE_W)
    for ph in "ABC":
        hs, ls = FETS[ph]
        r.route_net(net(f"GL{ph}"), width=GATE_W, name=f"GL{ph}")
        r.route_net(net(f"Net-({ls}-G)"), width=GATE_W)
    r.drain()
    log(f"routing: gate loops done ({len(r.routes)} routes)")
    if stages < 3:
        return

    # 3. driver supply and buck
    for n in SUPPLY:
        if n in r.code:
            r.route_net(net(n))
    r.drain()
    log(f"routing: supply nets done ({len(r.routes)} routes)")
    if stages < 4:
        return

    # 4. GND: a via per pad
    r.route_net(net("GND"), plane=True)
    r.drain()
    log(f"routing: GND vias done ({len(r.routes)} routes)")
    if stages < 5:
        return

    # 5. the rest, shortest first (bounding box half-perimeter of the net's pads)
    pads = {}
    for fp in r.b.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() > 0:
                pads.setdefault(p.GetNetCode(), []).append(r.P(p.GetPosition()))
    rest = []
    for code, pts in pads.items():
        name = r.netinfo[code]["name"]
        if name in done or len(pts) < 2 or name.startswith("unconnected-"):
            continue                      # (a connector's mounting tabs share an "unconnected" net)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        rest.append((max(xs) - min(xs) + max(ys) - min(ys), code))
    rest.sort()
    for _, code in rest:
        r.route_net(code)
    r.drain()
    log(f"routing: all nets tried ({len(r.routes)} routes, {len(r.failed)} failures)")


def units(r):
    """The same plan as data for gen/fastroute.py: an ordered list of routing units. Every unit is
    re-routed in every negotiation round, so the order only decides who goes first within a round."""
    out = []

    def net(net_name, **kw):
        out.append(dict(kind="net", net=net_name, **kw))

    for ph in "ABC":                                                   # Kelvin pairs
        net(f"SP_{ph}", name=f"SP_{ph}")
        net(f"SN_{ph}", name=f"SN_{ph}", attract=f"SP_{ph}", pair=2.0)   # leaving SP's side costs 2×
    for ph in "ABC":                                                   # gate loops
        hs, ls = FETS[ph]
        net(f"GH{ph}", width=GATE_W, name=f"GH{ph}")
        out.append(dict(kind="explicit", net=f"PHASE_{ph}", src=[("U201", DRV_SH[ph])],
                        tgt=[(hs, n) for n in HS_SOURCES], width=GATE_W, name=f"SH{ph}", attract=f"GH{ph}",
                        pair=1.5))
        net(f"Net-({hs}-G)", width=GATE_W)
    for ph in "ABC":
        hs, ls = FETS[ph]
        net(f"GL{ph}", width=GATE_W, name=f"GL{ph}")
        net(f"Net-({ls}-G)", width=GATE_W)
    # the buck's input loop first: VIN (pin 43) straight to its 1 µF, before the rest of V_BUS
    out.append(dict(kind="explicit", net="VBUS", src=[("U201", "43")], tgt=[("C203", "1")], width=0.3, name="VIN"))
    for n in SUPPLY:                                                   # driver supply and buck
        if n in r.code:
            net(n)
    out.append(dict(kind="plane", net="GND"))                          # a via per GND pad
    net("+3V3", width=0.25)                                            # the logic supplies, V_BUS feeds
    net("+3.3VA", width=0.2)
    net("VBUS")
    done = {u["net"] for u in out if u["kind"] != "explicit"}       # PHASE_x still needs its own tree
    pads = {}
    for fp in r.b.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() > 0:
                pads.setdefault(p.GetNetCode(), []).append(r.P(p.GetPosition()))
    rest = []
    for code, pts in pads.items():
        name = r.netinfo[code]["name"]
        if name in done or len(pts) < 2 or name.startswith("unconnected-"):
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        rest.append((max(xs) - min(xs) + max(ys) - min(ys), name))
    for _, nm in sorted(rest):                                         # the rest, shortest first
        net(nm)
    return out
