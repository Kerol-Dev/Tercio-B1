"""Drawing helpers shared by the B1 sheets.

Coordinates are millimetres on KiCad's 1.27 mm grid; G = 2.54 mm.
Two-pin parts from Device: (R, C, L, ...) have pin 1 at the top when
rot = 0 and on the left when rot = 90.
"""
from __future__ import annotations

from gen.catalog import Kit
from gen.model import Sheet

G = 2.54


def vert(part, top, bottom, stub=G):
    """Connect a vertical two-pin part: pin 1 (top) and pin 2 (bottom)."""
    part[1] = top
    part[2] = bottom
    if stub != G:
        part.stub = stub
    return part


def horiz(part, left, right):
    part[1] = left
    part[2] = right
    return part


def rail(sh: Sheet, y: float, xs: list[float]):
    """Horizontal rail through the x positions, split at each so attachments land on segment ends."""
    xs = sorted(set(xs))
    for a, b in zip(xs, xs[1:]):
        sh.wire((a, y), (b, y))
    for x in xs[1:-1]:
        sh.junction(x, y)


def column(sh: Sheet, x: float, ys: list[float]):
    ys = sorted(set(ys))
    for a, b in zip(ys, ys[1:]):
        sh.wire((x, a), (x, b))
    for y in ys[1:-1]:
        sh.junction(x, y)


def rc_lowpass(k: Kit, x: float, y: float, net_in: str, net_out: str, r: str, c: str,
               rpkg="0402", cpkg="0402", ground="GND"):
    """Series R (horizontal, centred at x) into a shunt C to ground; output label to the right."""
    sh = k.sh
    rr = k.R(r, (x, y), rot=90, pkg=rpkg)
    rr[1] = net_in
    p2 = rr.wire_to(2, net_out)
    cx = p2[0] + 2 * G
    cc = k.C(c, (cx, y + 3 * G), pkg=cpkg)  # top pin 1.5 grid below the wire
    top = cc.wire_to(1, net_out)
    cc[2] = ground
    sh.wire(p2, (cx, y))
    sh.wire((cx, y), top)
    sh.wire((cx, y), (cx + 2 * G, y))
    sh.junction(cx, y)
    sh.label(net_out, cx + 2 * G, y, 0)
    return rr, cc


def divider(k: Kit, x: float, y: float, top_net: str, mid_net: str, bot_net: str,
            r_top: str, r_bot: str, pkg_top="0402", pkg_bot="0402", cap: str | None = None,
            cap_pkg="0402", dnp=False, top_wired=False):
    """Vertical divider at x: R_top centred at y, R_bot 4 grid below, optional C from mid to ground."""
    sh = k.sh
    rt = k.R(r_top, (x, y), pkg=pkg_top, dnp=dnp)
    if top_wired:
        rt.wire_to(1, top_net)  # the caller draws the wire to pin 1
    else:
        rt[1] = top_net
    a = rt.wire_to(2, mid_net)
    rb = k.R(r_bot, (x, y + 4 * G), pkg=pkg_bot, dnp=dnp)
    b = rb.wire_to(1, mid_net)
    rb[2] = bot_net
    ym = y + 2 * G
    sh.wire(a, (x, ym))
    sh.wire((x, ym), b)
    sh.junction(x, ym)
    xc = x + 5 * G  # leave room for R_bot's reference/value text
    sh.wire((x, ym), (xc, ym))
    parts = [rt, rb]
    if cap:
        cc = k.C(cap, (xc, y + 4 * G), pkg=cap_pkg, dnp=dnp)
        t = cc.wire_to(1, mid_net)
        cc[2] = bot_net
        sh.wire((xc, ym), t)
        sh.wire((xc, ym), (xc + 5 * G, ym))
        sh.junction(xc, ym)
        sh.label(mid_net, xc + 5 * G, ym, 0)
        parts.append(cc)
    else:
        sh.label(mid_net, xc, ym, 0)
    return parts
