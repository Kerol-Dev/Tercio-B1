"""Power copper, planes and via arrays — the hand-specified part of the layout.

Stackup (6 layers): F.Cu (2 oz) · In1 GND plane · In2 V_BUS (power half) / phase / signal + GND ·
In3 signal, then a +3V3 fill (logic half) / GND fill (power half) · In4 GND plane · B.Cu (2 oz).
+3V3 is routed like any net; the In3 fill after routing only adds copper to it.
Per half-bridge on F.Cu: V_BUS over the high-side drain and the slot cap's V_BUS pad,
a GND column for the slot caps' returns and the shunt's GND pad (stitched to In1),
the phase node between the FETs with a via row down to phase pours on In2 and B.Cu
that reach the motor pad, and LSRC from the low-side sources to shunt pad 1.
"""
import pcbnew

from .board import LEGS, SHUNT_DX, Y_HS, Y_LS

W2 = 23.0 - 0.3   # zone edge inset from the board edge


def rect(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def pour(p, net, layer, pts, **kw):
    """A power pour. gen/router.py treats foreign tracks inside it as very expensive (pours stay whole)."""
    p.zone(net, layer, pts, **kw)


def pours(p):
    """Fills added after routing (they would block the autorouter): GND, and +3V3 on In3 under the logic."""
    p.zone("GND", "In2.Cu", rect(-W2, -W2, W2, W2), priority=0, clearance=0.2, name="GND (In2)")
    p.zone("+3V3", "In3.Cu", rect(-W2, -W2, W2, 3.0), priority=1, clearance=0.2, name="3V3 fill (In3)")
    p.zone("GND", "In3.Cu", rect(-W2, -W2, W2, W2), priority=0, clearance=0.2, name="GND (In3)")
    p.zone("GND", "B.Cu", rect(-W2, -W2, W2, W2), priority=0, clearance=0.2, name="GND (bottom)")
    p.zone("GND", "F.Cu", rect(-W2, -W2, W2, 3.1), priority=0, clearance=0.2, name="GND (top logic)")


def build(p):
    """Copper that exists during routing: the In1 GND plane, In2 V_BUS/phase and the power-stage pours."""
    # ---- planes ---------------------------------------------------------------------------------------
    p.zone("GND", "In1.Cu", rect(-W2, -W2, W2, W2), priority=0, clearance=0.2, name="GND plane")
    p.zone("GND", "In4.Cu", rect(-W2, -W2, W2, W2), priority=0, clearance=0.2, name="GND plane (In4)")
    # In3 is a signal layer everywhere: under the logic half the MCU's fan-out needs it more than +3V3
    # needs a plane (+3V3 is routed, then In3's leftover space is filled with +3V3 by pours())
    for L, t in ((pcbnew.In1_Cu, pcbnew.LT_POWER), (pcbnew.In2_Cu, pcbnew.LT_MIXED), (pcbnew.In3_Cu, pcbnew.LT_SIGNAL),
                 (pcbnew.In4_Cu, pcbnew.LT_POWER)):
        p.board.SetLayerType(L, t)
    # under the power stage from y 3.0, with a finger up to the XT30 + pin (left); In2 right of it (under
    # the DRV, the encoder and the MCU) stays free for the MCU's fan-out, gate-drive and sense routes
    vbus_in2 = [(-W2, -3.2), (-7.4, -3.2), (-7.4, 3.0), (W2, 3.0), (W2, 13.8),
                (16.8, 13.8), (16.8, 10.6), (-16.9, 10.6), (-16.9, 13.8), (-W2, 13.8)]
    pour(p, "VBUS", "In2.Cu", vbus_in2, priority=1, clearance=0.3, name="VBUS plane (In2)")

    # ---- per half-bridge ----------------------------------------------------------------------------------
    for ph, xf in LEGS.items():
        xs = xf + SHUNT_DX
        x_left = -W2 if ph == "A" else xs - 1.85
        x_right = W2 if ph == "C" else xf + 2.6
        pour(p, "VBUS", "F.Cu", rect(x_left, 3.45, x_right, 6.35), priority=2, clearance=0.3, name=f"VBUS {ph}")
        pour(p, "GND", "F.Cu", rect(xs - 1.85, 6.85, xs + 1.85, Y_LS - 2.1), priority=2, clearance=0.25, name=f"GND return {ph}")
        pour(p, f"PHASE_{ph}", "F.Cu", rect(xf - 2.6, Y_HS + 1.95, xf + 2.6, Y_LS + 1.35), priority=3, clearance=0.3,
               name=f"PHASE_{ph} (top)")
        for layer in ("In2.Cu", "B.Cu"):
            pour(p, f"PHASE_{ph}", layer, rect(xf - 2.6, Y_HS + 2.3, xf + 2.6, W2), priority=3, clearance=0.3,
                   name=f"PHASE_{ph} ({layer})")
        pour(p, f"LSRC_{ph}", "F.Cu", rect(xs - 1.85, Y_LS + 2.15, xf + 1.1, Y_LS + 3.55), priority=4, clearance=0.25,
               name=f"LSRC_{ph}")
        # phase via row in the gap between the high-side sources and the low-side drain pad
        for i in range(4):
            p.via(f"PHASE_{ph}", (xf - 2.0 + i * 1.0, Y_HS + 3.78), drill=0.3, size=0.55)
        # GND column → In1 plane
        for dx in (-1.0, 1.0):
            for y in (Y_HS + 2.2, Y_LS - 3.2):
                p.via("GND", (xs + dx, y), drill=0.3, size=0.6)
        # V_BUS strip → In2 plane
        for dx in (-0.9, 0.9):
            p.via("VBUS", (xf + dx, 3.95), drill=0.3, size=0.6)

    # ---- edge cap columns: GND between the two caps, V_BUS at the outer ends --------------------------------
    for x1, x2 in ((-W2, -17.05), (16.75, W2)):
        pour(p, "GND", "F.Cu", rect(x1, 6.85, x2, 10.15), priority=2, clearance=0.25, name="GND edge caps")
        pour(p, "VBUS", "F.Cu", rect(x1, 11.75, x2, 13.75), priority=2, clearance=0.3, name="VBUS edge caps")
        xm = (x1 + x2) / 2
        for dx in (-0.8, 0.8):
            p.via("GND", (xm + dx, 8.5), drill=0.3, size=0.6)
            p.via("VBUS", (xm + dx, 13.2), drill=0.3, size=0.6)
