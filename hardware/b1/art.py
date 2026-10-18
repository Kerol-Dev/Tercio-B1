"""Silkscreen — the Tercio identity and the labels someone holding the board needs, nothing else.

Type is IBM Plex, the website's: Plex Sans Condensed for the wordmark and labels, as filled polygons
(gen/fonttext.py), so the gerbers carry exactly these shapes and nobody needs the font installed.
Sizes stay at or above JLC's legend minimums (lines ≥ 0.15 mm, type ≥ 0.9 mm cap height).

Top (what you see once the board is on a motor): the mark and name, phase letters, connector names,
input voltage, LED meaning. Bottom (bring-up): the identity and spec line, test-point names, SWD pad
order, solder-jumper meaning, connector pinouts.

Every item goes through `Planner`, which keeps it off pads (0.25 mm), part bodies, holes, the board
edge and the other labels, searching outward from where it belongs. Nothing is forced: an item with
no room is left out and listed in the layout log.
"""
from __future__ import annotations

import math

import pcbnew

from gen import fonttext as ft

SILK = {"T": pcbnew.F_SilkS, "B": pcbnew.B_SilkS}
EDGE = 23.0


def _circle(cx, cy, r, n=72):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _capsule(a, b, w, n=16):
    """Stadium around segment a-b, width w (a round-capped stroke)."""
    (x1, y1), (x2, y2) = a, b
    ang = math.atan2(y2 - y1, x2 - x1)
    r = w / 2
    pts = []
    for i in range(n + 1):
        t = ang + math.pi / 2 + math.pi * i / n
        pts.append((x1 + r * math.cos(t), y1 + r * math.sin(t)))
    for i in range(n + 1):
        t = ang - math.pi / 2 + math.pi * i / n
        pts.append((x2 + r * math.cos(t), y2 + r * math.sin(t)))
    return pts


def mark_shapes(size):
    """The Tercio mark (Tercio-web Logo.astro, viewBox 32): ring r 14 stroke 2.2, T strokes 3 with round
    caps. Shapes centred on (0, 0), y down, as (outline, holes)."""
    k = size / 32.0
    ring = (_circle(0, 0, (14 + 1.1) * k), [_circle(0, 0, (14 - 1.1) * k)])
    bar = (_capsule(((9.5 - 16) * k, (11 - 16) * k), ((22.5 - 16) * k, (11 - 16) * k), 3 * k), [])
    stem = (_capsule((0, (11 - 16) * k), (0, (23.5 - 16) * k), 3 * k), [])
    return [ring, bar, stem]


class Planner:
    """Free-space bookkeeping for one side's silkscreen, in layout mm."""

    def __init__(self, p, side):
        self.p, self.side, self.layer = p, side, SILK[side]
        cu = pcbnew.F_Cu if side == "T" else pcbnew.B_Cu
        crt = pcbnew.F_CrtYd if side == "T" else pcbnew.B_CrtYd
        self.obs = []
        for fp in p.board.GetFootprints():
            if fp.IsFlipped() == (side == "B"):
                cy = fp.GetCourtyard(crt)
                # courtyards are body + 0.25 mm: silk may come within ~0.1 mm of the body, never onto it
                self.obs.append(self._box(cy.BBox() if cy.OutlineCount() else fp.GetBoundingBox(False), -0.15))
            for pad in fp.Pads():
                if pad.IsOnLayer(cu) or pad.GetDrillSizeX() > 0:
                    self.obs.append(self._box(pad.GetBoundingBox(), 0.25))
            for item in fp.GraphicalItems():          # the footprint's own outline and marks on this silk
                if item.GetLayer() == self.layer:
                    self.obs.append(self._box(item.GetBoundingBox(), 0.15))
        self.labels = []
        self.missed = []

    def _box(self, bb, m):
        x1, y1 = pcbnew.ToMM(bb.GetLeft()) - self.p.ox, pcbnew.ToMM(bb.GetTop()) - self.p.oy
        x2, y2 = pcbnew.ToMM(bb.GetRight()) - self.p.ox, pcbnew.ToMM(bb.GetBottom()) - self.p.oy
        return (x1 - m, y1 - m, x2 + m, y2 + m)

    def free(self, r, gap=0.3):
        x1, y1, x2, y2 = r
        e = EDGE - 0.5
        if x1 < -e or y1 < -e or x2 > e or y2 > e:
            return False
        for cx, cy in ((-20, -20), (20, -20), (-20, 20), (20, 20)):      # rounded corners (r 3)
            nx, ny = min(max(cx, x1), x2), min(max(cy, y1), y2)
            if abs(nx) > 20 and abs(ny) > 20 and math.hypot(nx - cx, ny - cy) > 3 - 0.5:
                return False
        for o in self.obs:
            if x1 < o[2] and x2 > o[0] and y1 < o[3] and y2 > o[1]:
                return False
        for o in self.labels:
            if x1 < o[2] + gap and x2 > o[0] - gap and y1 < o[3] + gap and y2 > o[1] - gap:
                return False
        return True

    def find(self, w, h, near, radius=4.0, step=0.1, rots=(0,), prefer=(0.0, 0.0), accept=None):
        """Centre and rotation of the free w × h box nearest to `near` (rot 90 swaps w and h).
        `prefer` biases the search direction (unit vector): ties go that way."""
        n = int(radius / step)
        cands = sorted(((i * step, j * step) for i in range(-n, n + 1) for j in range(-n, n + 1)
                        if (i * i + j * j) * step * step <= radius * radius),
                       key=lambda d: math.hypot(*d) - 0.3 * (d[0] * prefer[0] + d[1] * prefer[1]))
        for dx, dy in cands:
            for rot in rots:
                ww, hh = (w, h) if rot == 0 else (h, w)
                cx, cy = near[0] + dx, near[1] + dy
                r = (cx - ww / 2, cy - hh / 2, cx + ww / 2, cy + hh / 2)
                if self.free(r) and (accept is None or accept(r)):
                    return cx, cy, rot, r
        return None

    def claim(self, r):
        self.labels.append(r)

    # ---- drawing (u, v: the viewer's frame — the bottom is drawn as seen from below) -------------
    def _to_board(self, cx, cy, u, v, rot):
        if rot:
            u, v = v, -u
        return (cx - u if self.side == "B" else cx + u), cy + v

    def shapes(self, shapes, cx, cy, rot=0):
        for outline, holes in shapes:
            self.p.poly(self.layer, [self._to_board(cx, cy, u, v, rot) for u, v in outline],
                        [[self._to_board(cx, cy, u, v, rot) for u, v in h] for h in holes])

    @staticmethod
    def text_shapes(s, cap, face="display-bold", tracking=0.0):
        cs, w = ft.font(face).layout(s, cap, tracking)
        cs = [[(x - w / 2, y + cap / 2) for x, y in c] for c in cs]     # centred on the cap box
        return ft.nest(cs), w

    def text(self, s, cap, near, face="display-bold", radius=3.0, rots=(0,), tracking=0.0, prefer=(0.0, 0.0),
             what=None, rivals=()):
        """Place s near `near`; with `rivals` (other pads it could be read as naming), only where the
        label's nearest edge is clearly closer to its own pad than to any rival."""
        shapes, w = self.text_shapes(s, cap, face, tracking)

        def gap(r, pt):
            return math.hypot(max(r[0] - pt[0], 0, pt[0] - r[2]), max(r[1] - pt[1], 0, pt[1] - r[3]))
        accept = (lambda r: all(gap(r, near) + 0.4 < gap(r, q) for q in rivals)) if rivals else None
        hit = self.find(w + 0.1, cap + 0.1, near, radius, rots=rots, prefer=prefer, accept=accept)
        if hit is None:
            self.missed.append(what or s)
            return None
        cx, cy, rot, r = hit
        self.shapes(shapes, cx, cy, rot)
        self.claim(r)
        return r

    def block(self, items, near, radius=6.0, rots=(0,), what="block"):
        """Several shape groups laid out as one rigid w × h block: items = (shapes, du, dv) relative to
        the block centre, plus the block size; placed where the whole box is free."""
        shapes_list, (w, h) = items
        hit = self.find(w, h, near, radius, rots=rots)
        if hit is None:
            self.missed.append(what)
            return None
        cx, cy, rot, r = hit
        for shapes, du, dv in shapes_list:
            moved = [([(u + du, v + dv) for u, v in o], [[(u + du, v + dv) for u, v in hh] for hh in hs])
                     for o, hs in shapes]
            self.shapes(moved, cx, cy, rot)
        self.claim(r)
        return r


def _identity(cap, tag, spec=()):
    """The identity: mark, "Tercio" (Plex Sans Condensed SemiBold, like the website) and the product tag
    in bold; spec lines (small, bold) to the right after a hairline. One row, centred on (0, 0).
    Returns ((shapes, du, dv)…, (w, h))."""
    ts = Planner.text_shapes
    m = cap * 1.4                                    # mark diameter
    gh, gap = cap * 0.4, cap * 0.28
    name, wn = ts("Tercio", cap, "display")
    tagg, wt = ts(tag, cap, "display-bold")
    w = m + gh + wn + gap + wt
    # laid out from the mark's left edge (u = 0), centred at the end
    items = [(mark_shapes(m), m / 2, 0.0), (name, m + gh + wn / 2, 0.0), (tagg, m + gh + wn + gap + wt / 2, 0.0)]
    h = m
    if spec:
        cs = cap * 0.42
        lines = [ts(t, cs, "display-bold", 0.03) for t in spec]
        lh = cs * 1.55
        col_h = cs + lh * (len(lines) - 1)
        x_rule = w + cap * 0.45
        items.append(([([(x_rule - 0.075, -m / 2 + 0.1), (x_rule + 0.075, -m / 2 + 0.1), (x_rule + 0.075, m / 2 - 0.1),
                         (x_rule - 0.075, m / 2 - 0.1)], [])], 0.0, 0.0))
        x0 = x_rule + cap * 0.45
        for i, (sh, ws) in enumerate(lines):
            items.append((sh, x0 + ws / 2, -col_h / 2 + cs / 2 + i * lh))
        w = x0 + max(ws for _, ws in lines)
        h = max(m, col_h)
    items = [(sh, du - w / 2, dv) for sh, du, dv in items]
    return items, (w + 0.2, h + 0.2)


def _arrow(left, h):
    """A small solid triangle, h tall, pointing left or right, centred on (0, 0)."""
    w = h * 0.8
    pts = [(-w / 2, 0), (w / 2, -h / 2), (w / 2, h / 2)] if left else [(w / 2, 0), (-w / 2, -h / 2), (-w / 2, h / 2)]
    return [(pts, [])]


def _pointer_label(cap):
    """"◀ CAN" over "AUX ▶": names the two top-edge connectors from the gap between them."""
    ts = Planner.text_shapes
    can, wc = ts("CAN", cap)
    aux, wa = ts("AUX", cap)
    tri = cap * 0.85
    g = cap * 0.35
    w = max(tri + g + wc, wa + g + tri)
    lh = cap * 1.45
    items = [(_arrow(True, tri), -w / 2 + tri * 0.4, -lh / 2), (can, -w / 2 + tri * 0.8 + g + wc / 2, -lh / 2),
             (aux, w / 2 - tri * 0.8 - g - wa / 2, lh / 2), (_arrow(False, tri), w / 2 - tri * 0.4, lh / 2)]
    return items, (w + 0.2, lh + cap + 0.2)


def _pinout(name, cells, cap):
    """One connector's pinout: its name, then pin numbers (small, bold) over the signal names."""
    ts = Planner.text_shapes
    nc = max(cap * 0.83, 0.72)                        # pin numbers: bold, so the strokes stay ≥ 0.15 mm
    head = 2.9 * cap / 0.9
    pitch = 2.55 * cap / 0.9
    w = head + len(cells) * pitch
    h = nc + 0.22 + cap
    items = []
    sh, wn = ts(name, cap)
    items.append((sh, -w / 2 + wn / 2, h / 2 - cap / 2))
    for k, c in enumerate(cells):
        x = -w / 2 + head + pitch * (k + 0.5)
        sh, _ = ts(str(k + 1), nc)
        items.append((sh, x, -h / 2 + nc / 2))
        sh, _ = ts(c, cap)
        items.append((sh, x, h / 2 - cap / 2))
    y = -h / 2 + nc + 0.11                            # hairline between numbers and names
    items.append(([([(-w / 2 + head - 0.3, y - 0.075), (w / 2, y - 0.075), (w / 2, y + 0.075),
                     (-w / 2 + head - 0.3, y + 0.075)], [])], 0.0, 0.0))
    return items, (w + 0.2, h + 0.2)


def _serial(cap):
    """"S/N" and a white field to write a serial number on."""
    sh, wl = Planner.text_shapes("S/N", cap)
    fw, fh = 4.5, cap * 2.0
    g = cap * 0.5
    w = wl + g + fw
    field = [([(-fw / 2, -fh / 2), (fw / 2, -fh / 2), (fw / 2, fh / 2), (-fw / 2, fh / 2)], [])]
    return [(sh, -w / 2 + wl / 2, 0.0), (field, w / 2 - fw / 2, 0.0)], (w + 0.2, fh + 0.2)


def draw(p):
    top, bot = Planner(p, "T"), Planner(p, "B")
    from .board import LEGS

    # ---- top (seen on the motor): fixed-place labels first, the identity where room is left ---------
    for ph, x in LEGS.items():
        top.text(ph, 2.0, (x - 4.0, 20.6), radius=1.5, what=f"phase {ph} (top)")
    top.text("STATUS", 0.95, p.pad_xy("D401", "1"), radius=3.0, rots=(90,), prefer=(1, 0), what="status LED")
    top.text("FAULT", 0.95, p.pad_xy("D402", "1"), radius=3.0, rots=(90,), prefer=(1, 0), what="fault LED")
    # CAN in and AUX are named from the narrow gap between them, each word against its own connector
    jx = (p.pad_xy("J601", "1")[0] + p.pad_xy("J701", "8")[0]) / 2
    top.text("CAN", 0.9, (jx - 0.65, -21.1), radius=1.0, rots=(90,), prefer=(-1, 0), what="CAN in (top)")
    top.text("AUX", 0.9, (jx + 0.65, -21.1), radius=1.0, rots=(90,), prefer=(1, 0), what="AUX (top)")
    top.text("CAN", 1.1, (p.pad_xy("J602", "2")[0] - 2.1, p.pad_xy("J602", "2")[1]), radius=3.0, rots=(90,),
             what="CAN out (top)")
    top.text("10–52 V", 1.0, (p.pad_xy("J101", "2")[0] + 3.4, p.pad_xy("J101", "2")[1] - 3.0), radius=4.0,
             rots=(90, 0), what="input voltage")
    top.block(_identity(1.6, "B1"), (1.0, 0.6), radius=9.0, rots=(0, 90), what="identity (top)")

    # ---- bottom (bring-up): labels that belong to a pad first, then the tables, then the identity -----
    for ph, x in LEGS.items():
        bot.text(ph, 2.0, (x - 4.0, 20.6), radius=1.5, what=f"phase {ph} (bottom)")
    tps = {"TP101": "VBUS", "TP102": "GND", "TP103": "5V", "TP104": "3V3", "TP105": "3VA", "TP106": "GND",
           "TP201": "SOA", "TP202": "SOB", "TP203": "SOC", "TP204": "GLA", "TP205": "GLB", "TP206": "GLC",
           "TP207": "SW", "TP208": "FLT"}
    for tp, name in tps.items():
        rivals = [p.pad_xy(t, "1") for t in tps if t != tp]
        bot.text(name, 0.9, p.pad_xy(tp, "1"), radius=3.5, rots=(0, 90), what=f"{tp} {name}", rivals=rivals)
    for num, name in zip("12345", ("3V3", "DIO", "CLK", "RST", "GND")):
        bot.text(name, 0.9, p.pad_xy("J401", num), radius=2.6, what=f"SWD {name}")
    bot.text("SWD", 1.1, p.pad_xy("J401", "3"), radius=6.0, rots=(90, 0), what="SWD title")
    bot.text("120R", 0.9, p.pad_xy("JP601", "1"), radius=3.5, rots=(0, 90), what="CAN termination jumper")
    bot.text("NTC", 0.9, p.pad_xy("JP701", "1"), radius=3.5, rots=(0, 90), what="aux NTC jumper")
    bot.block(_identity(1.9, "B1", ("FOC MOTOR DRIVER", "10–52 V · REV A")), (0.0, 6.35), radius=10.0,
              what="identity (bottom)")
    bot.block(_pinout("AUX", ["3V3", "A1", "A2", "A3", "A4", "A5", "AN", "GND"], 0.8), (-9.0, 10.5), radius=14.0,
              what="AUX pinout")
    bot.block(_pinout("CAN", ["NC", "H", "L", "GND"], 0.8), (10.0, 10.8), radius=14.0, what="CAN pinout")
    bot.block(_serial(0.9), (-16.0, 14.0), radius=14.0, what="serial field")


    missed = top.missed + bot.missed
    if missed:
        print("art: no room for " + ", ".join(missed))
