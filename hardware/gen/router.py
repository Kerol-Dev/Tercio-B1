"""Grid router with rip-up and reroute (numpy + heapq, runs inside KiCad's Python next to pcbnew).

Why our own: Freerouting 2.5 leaves ~180 of ~300 connections unrouted on this board, and the
power stage wants routes an autorouter does not know about (gate loops, Kelvin pairs, a via per
GND pad). The router works on KiCad's own geometry and writes ordinary KiCad tracks and vias.

Model
- Grid of `PITCH` mm over the board; layers F.Cu, In1.Cu (plane: via targets only), In2.Cu, B.Cu.
- Clearance: for every routing *profile* (net clearance, half width) and layer two owner rasters say
  which net's copper is within reach of each cell (-1 none, net code, -2 several / blocked for all):
  *hard* (pads, holes, fixed copper, escape corridors) and *soft* (the router's own tracks and vias,
  which can be ripped up). A cell is free for net N if both owners are -1 or N. Distances are exact
  from the real shapes to the cell centres, plus MARGIN for the grid and for 45° segments, so
  KiCad's DRC passes by construction.
- Zones are not copper while routing (they are filled afterwards). Foreign pours are walls except
  close to the connection's own pads (pads that sit inside a pour); a foreign via inside an
  outer-layer pour is not allowed. Own-net zones are targets.
- Fine-pitch IC pins get an escape corridor (virtual copper of the pin's net) straight out from the
  pad; lengths can be staggered per pin for clean fan-outs.
- Wide classes neck down to NECK_W within NECK_R of small pads.
- A* over (layer, cell, direction) with turn and via costs. Nets are joined island by island
  (initial islands from KiCad's connectivity, merged by the router's own routes); GND islands each
  drop their own via to the In1 plane.
- Rip-up: when a connection cannot be routed, it is searched again with the router's earlier routes
  passable at RIP_COST per cell; the routes it crosses are ripped up and their nets queued again
  (each net at most MAX_RIPS times).
- Pairs: a connection can be attracted to a named partner route (Kelvin SP/SN, gate GH + SH return).
- Routes stay in memory until finalize() writes them to the board as locked tracks and vias.
"""
from __future__ import annotations

import fnmatch
import heapq
import math

import numpy as np
import pcbnew

PITCH = 0.05
MARGIN = 0.04
NECK_W = 0.2
NECK_R = 1.5          # must clear the neighbouring pins' escape corridors (0.5 mm + clearance)
EDGE_CLEAR = 0.3
VIA_COST = 1.2
POUR_COST = 4.0      # inside a foreign pour, only near the connection's own pads (pad escapes)
POUR_ESCAPE = 1.2
RIP_COST = 6.0       # per cell of someone else's route, when searching for what to rip up
MAX_RIPS = 8
HOLE_GAP = 0.25      # drill to drill (board rule min_hole_to_hole)
ESCAPE = 0.5          # escape corridor beyond fine-pitch IC pads (virtual copper of the pin's net)
FINE_PITCH = 0.65
TURN_COST = (0.0, 0.12, 0.5)          # 0°, 45°, 90° direction change (mm-equivalent)
LAYER_MUL = {0: 1.0, 2: 1.35, 3: 1.35, 5: 1.0}  # inner signal layers are GND pours under the logic: sparingly
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
# 6 layers: F (power stage, parts) · In1 GND plane · In2 signal (+ V_BUS plane under the power stage) ·
# In3 signal · In4 GND plane · B (parts)
F, IN1, IN2, IN3, IN4, B = 0, 1, 2, 3, 4, 5
KLAYER = {F: pcbnew.F_Cu, IN1: pcbnew.In1_Cu, IN2: pcbnew.In2_Cu, IN3: pcbnew.In3_Cu, IN4: pcbnew.In4_Cu, B: pcbnew.B_Cu}
LIDX = {v: k for k, v in KLAYER.items()}
ROUTE_LAYERS = (F, IN2, IN3, B)
BLOCK = -2


def mm(v):
    return pcbnew.ToMM(v)


class Item:
    """Copper the router knows: kind 'poly' (pad outline), 'seg' (track) or 'circ' (via / hole).
    virtual: an escape corridor (reserved for its net, not real copper); route: owning route id."""
    __slots__ = ("net", "layers", "kind", "geom", "clear", "hw", "virtual", "route")

    def __init__(self, net, layers, kind, geom, clear, hw=0.0, virtual=False, route=None):
        self.net, self.layers, self.kind, self.geom, self.clear, self.hw = net, layers, kind, geom, clear, hw
        self.virtual, self.route = virtual, route

    def bbox(self):
        g = self.geom
        if self.kind == "poly":
            xs = [p[0] for poly in g for p in poly]
            ys = [p[1] for poly in g for p in poly]
            return min(xs), min(ys), max(xs), max(ys)
        if self.kind == "seg":
            (x1, y1), (x2, y2) = g
            return min(x1, x2) - self.hw, min(y1, y2) - self.hw, max(x1, x2) + self.hw, max(y1, y2) + self.hw
        (x, y), r = g
        return x - r, y - r, x + r, y + r

    def dist(self, px, py):
        """Distance from points to the copper (0 inside)."""
        g = self.geom
        if self.kind == "circ":
            (x, y), r = g
            return np.maximum(np.hypot(px - x, py - y) - r, 0.0)
        if self.kind == "seg":
            return np.maximum(seg_dist(px, py, *g[0], *g[1]) - self.hw, 0.0)
        best = None
        for poly in g:
            d = poly_dist(px, py, poly)
            best = d if best is None else np.minimum(best, d)
        return best


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return np.hypot(px - x1, py - y1)
    t = np.clip(((px - x1) * dx + (py - y1) * dy) / L2, 0.0, 1.0)
    return np.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def poly_dist(px, py, poly):
    """Distance to a closed polygon (0 inside), vectorised over points."""
    n = len(poly)
    d = None
    inside = np.zeros(np.shape(px), dtype=bool)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        e = seg_dist(px, py, x1, y1, x2, y2)
        d = e if d is None else np.minimum(d, e)
        cond = ((y1 > py) != (y2 > py))
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = x1 + (py - y1) * (x2 - x1) / (y2 - y1 if y2 != y1 else 1e-12)
        inside ^= cond & (px < xint)
    return np.where(inside, 0.0, d)


def box_erode(mask, r):
    """Erode a boolean mask by a (2r+1)² square (integral image)."""
    if r <= 0:
        return mask.copy()
    m = mask.astype(np.int32)
    H, W = m.shape
    ii = np.zeros((H + 1, W + 1), dtype=np.int32)
    ii[1:, 1:] = m.cumsum(0).cumsum(1)
    y0 = np.clip(np.arange(H) - r, 0, H)
    y1 = np.clip(np.arange(H) + r + 1, 0, H)
    x0 = np.clip(np.arange(W) - r, 0, W)
    x1 = np.clip(np.arange(W) + r + 1, 0, W)
    s = ii[y1][:, x1] - ii[y0][:, x1] - ii[y1][:, x0] + ii[y0][:, x0]
    full = (y1 - y0)[:, None] * (x1 - x0)[None, :]
    return (s == full) & ((y1 - y0) == 2 * r + 1)[:, None] & ((x1 - x0) == 2 * r + 1)[None, :]


class Router:
    def __init__(self, board, classes, origin=(150.0, 100.0), size=(46.0, 46.0), holes=(), hole_keepout=3.0,
                 escape=None, via_keepouts=(), patterns=None, log=print):
        self.b, self.ox, self.oy = board, origin[0], origin[1]
        self.via_keepouts = via_keepouts              # rects (x1, y1, x2, y2) with no vias (e.g. under silk art)
        # net classes from the .kicad_pro ("classes" list + "netclass_patterns"): pcbnew's NETCLASS objects
        # are not wrapped, and in a process that saved the board before, LoadBoard keeps the cached project
        # (every net "Default"), so the router matches the patterns itself
        self.classes = {c["name"]: c for c in classes}
        self.patterns = [(pp["pattern"], pp["netclass"]) for pp in (patterns or [])]
        self.w2, self.h2 = size[0] / 2, size[1] / 2
        self.nx = int(round(size[0] / PITCH)) + 1
        self.ny = int(round(size[1] / PITCH)) + 1
        self.NK = self.nx * self.ny
        self.xs = -self.w2 + np.arange(self.nx) * PITCH
        self.ys = -self.h2 + np.arange(self.ny) * PITCH
        self.holes, self.hole_keepout = holes, hole_keepout
        self.escape = escape or {}                    # (ref, pad) -> corridor length (staggered fan-outs)
        self.log = log
        self.items: list[Item] = []                   # hard copper
        self.hard: dict[tuple, dict] = {}             # profile -> {layer: owner raster}
        self.soft: dict[tuple, dict] = {}
        self.routes: dict[int, dict] = {}             # route id -> record
        self._rid = 0
        self.netinfo = {}
        self.failed = []
        self.opts = {}                                # net -> route_net options (for re-routing)
        self.explicit = {}                            # net -> [explicit pad-to-pad connections]
        self.rips = {}                                # net -> times ripped
        self.pending = []                             # nets whose routes were ripped up
        self.nfail = {}
        self._pad_keep = {}
        self._isl0 = {}
        self.why = ""
        self.fps = {f.GetReference(): f for f in board.GetFootprints()}
        for code in range(1, board.GetNetCount()):
            net = board.FindNet(code)
            if net is None or not net.GetNetname():
                continue
            name = net.GetNetname()
            cls = next((nc for pat, nc in self.patterns if fnmatch.fnmatchcase(name, pat)), None) \
                if self.patterns else net.GetNetClassName()
            cls = cls or "Default"
            c = self.classes.get(cls, self.classes["Default"])
            self.netinfo[code] = dict(name=net.GetNetname(), cls=cls, clear=c["clearance"], width=c["track_width"],
                                      via=c["via_diameter"], drill=c["via_drill"])
        self.code = {v["name"]: k for k, v in self.netinfo.items()}
        self._load_items()
        self._load_zones()
        board.BuildConnectivity()
        self.conn = board.GetConnectivity()

    # ---- geometry in -----------------------------------------------------------------------------
    def P(self, v):
        return mm(v.x) - self.ox, mm(v.y) - self.oy

    def _clear(self, net):
        return self.netinfo[net]["clear"] if net in self.netinfo else 0.2

    def _load_items(self):
        b = self.b
        for fp in b.GetFootprints():
            for pad in fp.Pads():
                net = pad.GetNetCode() if pad.GetNetCode() > 0 else BLOCK
                if pad.GetNetname().startswith("unconnected-"):
                    net = BLOCK                       # a no-connect pin: just an obstacle
                layers = [i for i, kl in KLAYER.items() if pad.IsOnLayer(kl)]
                for L in layers:
                    ps = pcbnew.SHAPE_POLY_SET()
                    pad.TransformShapeToPolygon(ps, KLAYER[L], 0, pcbnew.FromMM(0.003), pcbnew.ERROR_OUTSIDE)
                    polys = []
                    for oi in range(ps.OutlineCount()):
                        ol = ps.Outline(oi)
                        polys.append([self.P(ol.CPoint(k)) for k in range(ol.PointCount())])
                    if polys:
                        self.items.append(Item(net, (L,), "poly", polys, self._clear(net)))
                if pad.HasHole():
                    ds = pad.GetDrillSize()
                    r = mm(max(ds.x, ds.y)) / 2
                    hole_net = net if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH else BLOCK
                    self.items.append(Item(hole_net, ROUTE_LAYERS, "circ", (self.P(pad.GetPosition()), r), 0.2))
        self._load_corridors()
        for t in b.GetTracks():
            net = t.GetNetCode()
            if t.Type() == pcbnew.PCB_VIA_T:
                self.items.append(Item(net, tuple(KLAYER), "circ", (self.P(t.GetPosition()), mm(t.GetWidth(pcbnew.F_Cu)) / 2),
                                       self._clear(net)))
            else:
                self.items.append(Item(net, (LIDX[t.GetLayer()],), "seg", (self.P(t.GetStart()), self.P(t.GetEnd())),
                                       self._clear(net), mm(t.GetWidth()) / 2))

    def _load_corridors(self):
        """Fine-pitch IC pins get a corridor straight out from the pad, so an early route cannot
        run along the pin row and wall the other pins in."""
        for fp in self.b.GetFootprints():
            pads = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
            if len(pads) < 8:
                continue
            pos = [self.P(p.GetPosition()) for p in pads]
            pitch = min((math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(pos) for b in pos[i + 1:]
                         if math.hypot(a[0] - b[0], a[1] - b[1]) > 0.01), default=9)
            if pitch > FINE_PITCH:
                continue
            cx, cy = self.P(fp.GetPosition())
            for pad, (px, py) in zip(pads, pos):
                if pad.GetNetCode() <= 0 or pad.GetNetname().startswith("unconnected-"):
                    continue
                sz = pad.GetSize(pad.GetPrincipalLayer())
                sx, sy = mm(sz.x), mm(sz.y)
                if pad.GetOrientation().AsDegrees() % 180 > 45:
                    sx, sy = sy, sx
                dx, dy = px - cx, py - cy
                if max(sx, sy) > 2.0 or abs(dx) < 0.3 and abs(dy) < 0.3:
                    continue                      # exposed pad
                hwid = min(sx, sy) / 2
                esc = self.escape.get((fp.GetReference(), pad.GetNumber()), ESCAPE)
                # escape along the pad's long axis, away from the body (on a long two-row package the end
                # pins sit farther from the centre along the row than across it)
                if sx > sy * 1.2 or (abs(sx - sy) <= sy * 0.2 and abs(dx) > abs(dy)):
                    e = px + math.copysign(sx / 2, dx)
                    x1, x2 = sorted((e, e + math.copysign(esc, dx)))
                    rect = [(x1, py - hwid), (x2, py - hwid), (x2, py + hwid), (x1, py + hwid)]
                else:
                    e = py + math.copysign(sy / 2, dy)
                    y1, y2 = sorted((e, e + math.copysign(esc, dy)))
                    rect = [(px - hwid, y1), (px + hwid, y1), (px + hwid, y2), (px - hwid, y2)]
                # (GetPrincipalLayer() says F.Cu even for pads of a flipped footprint)
                L = F if pad.IsOnLayer(pcbnew.F_Cu) else B
                self.items.append(Item(pad.GetNetCode(), (L,), "poly", [rect], self._clear(pad.GetNetCode()),
                                       virtual=True))

    def _load_zones(self):
        """Zone owner rasters (priority resolved) and kinds: 1 = pour (outer / phase), 2 = plane."""
        shape = (self.ny, self.nx)
        self.zone_net = {L: np.full(shape, -1, np.int16) for L in KLAYER}
        self.zone_kind = {L: np.zeros(shape, np.int8) for L in KLAYER}
        X, Y = np.meshgrid(self.xs, self.ys)
        zones = [z for z in self.b.Zones() if not z.GetIsRuleArea() and z.GetNetCode() > 0]
        zones.sort(key=lambda z: z.GetAssignedPriority())
        for z in zones:
            ol = z.Outline().Outline(0)
            poly = [self.P(ol.CPoint(k)) for k in range(ol.PointCount())]
            inside = poly_dist(X, Y, poly) == 0
            for kl in z.GetLayerSet().CuStack():
                if kl not in LIDX:
                    continue
                L = LIDX[kl]
                net = z.GetNetCode()
                name = self.netinfo[net]["name"]
                plane = L in (IN1, IN4) or (L == IN2 and name == "VBUS") or (L == IN3 and name == "+3V3")
                self.zone_net[L][inside] = net
                self.zone_kind[L][inside] = 2 if plane else 1
        self._deep = {}

    def zone_deep(self, L, net, r=0.4):
        key = (L, net)
        if key not in self._deep:
            self._deep[key] = box_erode(self.zone_net[L] == net, int(math.ceil(r / PITCH))).ravel()
        return self._deep[key]

    # ---- owner rasters ----------------------------------------------------------------------------
    def profile(self, clear, hw):
        """(hard, soft) owner rasters for a routing profile."""
        key = (round(clear, 3), round(hw, 3))
        if key not in self.hard:
            hr = {L: np.full((self.ny, self.nx), -1, np.int16) for L in KLAYER}
            sr = {L: np.full((self.ny, self.nx), -1, np.int16) for L in KLAYER}
            for it in self.items:
                self._paint(it, key, hr)
            self._paint_static(key, hr)
            for rec in self.routes.values():
                for it in rec["items"]:
                    self._paint(it, key, sr)
            self.hard[key], self.soft[key] = hr, sr
        return self.hard[key], self.soft[key]

    def _window(self, x1, y1, x2, y2):
        i0 = max(0, int(math.floor((x1 + self.w2) / PITCH)))
        i1 = min(self.nx, int(math.ceil((x2 + self.w2) / PITCH)) + 1)
        j0 = max(0, int(math.floor((y1 + self.h2) / PITCH)))
        j1 = min(self.ny, int(math.ceil((y2 + self.h2) / PITCH)) + 1)
        return j0, j1, i0, i1

    def _paint(self, it, key, rs, clip=None):
        clear, hw = key
        D = max(clear, it.clear) + hw + MARGIN
        x1, y1, x2, y2 = it.bbox()
        j0, j1, i0, i1 = self._window(x1 - D, y1 - D, x2 + D, y2 + D)
        if clip:
            j0, j1, i0, i1 = max(j0, clip[0]), min(j1, clip[1]), max(i0, clip[2]), min(i1, clip[3])
        if j1 <= j0 or i1 <= i0:
            return
        X, Y = np.meshgrid(self.xs[i0:i1], self.ys[j0:j1])
        m = it.dist(X, Y) < D
        for L in it.layers:
            v = rs[L][j0:j1, i0:i1]
            cur = v[m]
            v[m] = np.where(cur == -1, it.net, np.where(cur == it.net, it.net, BLOCK))

    def _paint_static(self, key, rs):
        clear, hw = key
        X, Y = np.meshgrid(self.xs, self.ys)
        e = EDGE_CLEAR + hw + MARGIN
        m = (X < -self.w2 + e) | (X > self.w2 - e) | (Y < -self.h2 + e) | (Y > self.h2 - e)
        for hx, hy in self.holes:
            m |= np.hypot(X - hx, Y - hy) < self.hole_keepout + hw
        for L in KLAYER:
            rs[L][m] = BLOCK

    def _soft_items(self):
        for rec in self.routes.values():
            yield from rec["items"]

    def _repaint_soft(self, items):
        """Clear and repaint the soft rasters where `items` were (after a rip-up)."""
        for key, sr in self.soft.items():
            clear, hw = key
            for it in items:
                D = max(clear, it.clear) + hw + MARGIN
                x1, y1, x2, y2 = it.bbox()
                win = self._window(x1 - D, y1 - D, x2 + D, y2 + D)
                for L in it.layers:
                    sr[L][win[0]:win[1], win[2]:win[3]] = -1
                for other in self._soft_items():
                    ox1, oy1, ox2, oy2 = other.bbox()
                    Do = max(clear, other.clear) + hw + MARGIN
                    if ox2 + Do < x1 - D or ox1 - Do > x2 + D or oy2 + Do < y1 - D or oy1 - Do > y2 + D:
                        continue
                    self._paint(other, key, sr, clip=win)

    # ---- islands ---------------------------------------------------------------------------------------
    def _initial_islands(self, net):
        """Connected groups of `net` as built (pads, zones, fixed vias/tracks), from KiCad, cached."""
        if net in self._isl0:
            return self._isl0[net]
        pads = [p for fp in self.b.GetFootprints() for p in fp.Pads() if p.GetNetCode() == net]
        parent, objs = {}, {}

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for p in pads:
            k = p.m_Uuid.AsString()
            parent.setdefault(k, k)
            objs[k] = p
            for it in self.conn.GetConnectedItems(p):
                kk = it.m_Uuid.AsString()
                parent.setdefault(kk, kk)
                objs[kk] = it
                ra, rb = find(k), find(kk)
                if ra != rb:
                    parent[ra] = rb
        groups = {}
        for k in parent:
            groups.setdefault(find(k), []).append(objs[k])
        out = []
        for g in groups.values():
            isl = {"pads": [], "vias": [], "tracks": [], "zones": []}
            for o in g:
                t = o.Type()
                if t == pcbnew.PCB_PAD_T:
                    isl["pads"].append(o)
                elif t == pcbnew.PCB_VIA_T:
                    isl["vias"].append(self.P(o.GetPosition()))
                elif t == pcbnew.PCB_ZONE_T:
                    isl["zones"].append(o)
                elif LIDX.get(o.GetLayer()) is not None:
                    isl["tracks"].append((LIDX[o.GetLayer()], self.P(o.GetStart()), self.P(o.GetEnd())))
            if isl["pads"] or isl["zones"]:
                out.append(isl)
        self._isl0[net] = out
        return out

    def islands(self, net):
        """Current islands: the initial ones merged by this net's routes (with their geometry)."""
        base = self._initial_islands(net)
        parent = list(range(len(base)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        recs = [r for r in self.routes.values() if r["net"] == net]
        for r in recs:
            if not r["joins"]:
                continue
            ids = sorted(r["joins"])
            for i in ids[1:]:
                ra, rb = find(ids[0]), find(i)
                if ra != rb:
                    parent[ra] = rb
        groups = {}
        for i in range(len(base)):
            g = groups.setdefault(find(i), {"pads": [], "vias": [], "tracks": [], "zones": [], "ids": set()})
            for k in ("pads", "vias", "tracks", "zones"):
                g[k] += base[i][k]
            g["ids"].add(i)
        for rid, r in ((k, v) for k, v in self.routes.items() if v["net"] == net):
            if not r["joins"]:
                continue
            g = groups[find(min(r["joins"]))]
            g.setdefault("rtracks", []).extend((rid, L, p1, p2) for L, p1, p2, _ in r["segs"])
            g.setdefault("rvias", []).extend((rid, x, y) for x, y in r["vias"])
        return list(groups.values())

    # ---- cells -----------------------------------------------------------------------------------------
    def cell(self, x, y):
        i = int(round((x + self.w2) / PITCH))
        j = int(round((y + self.h2) / PITCH))
        return min(max(j, 0), self.ny - 1) * self.nx + min(max(i, 0), self.nx - 1)

    def xy(self, k):
        return float(self.xs[k % self.nx]), float(self.ys[k // self.nx])

    def pad_layers(self, pad):
        return [L for L in ROUTE_LAYERS if pad.IsOnLayer(KLAYER[L])]

    def pad_mask(self, pad, L, shrink=0.05):
        """Flat indices of cells inside a pad on layer L (shrunk a little)."""
        ps = pcbnew.SHAPE_POLY_SET()
        pad.TransformShapeToPolygon(ps, KLAYER[L], 0, pcbnew.FromMM(0.003), pcbnew.ERROR_INSIDE)
        if ps.OutlineCount() == 0:
            return np.array([], dtype=np.int64)
        polys = []
        for oi in range(ps.OutlineCount()):
            ol = ps.Outline(oi)
            polys.append([self.P(ol.CPoint(k)) for k in range(ol.PointCount())])
        xs = [p[0] for q in polys for p in q]
        ys = [p[1] for q in polys for p in q]
        j0, j1, i0, i1 = self._window(min(xs), min(ys), max(xs), max(ys))
        X, Y = np.meshgrid(self.xs[i0:i1], self.ys[j0:j1])
        inner = np.zeros(X.shape, bool)
        for poly in polys:
            n = len(poly)
            d = None
            for i in range(n):
                e = seg_dist(X, Y, *poly[i], *poly[(i + 1) % n])
                d = e if d is None else np.minimum(d, e)
            inner |= (poly_dist(X, Y, poly) == 0) & (d >= shrink)
        jj, ii = np.nonzero(inner)
        return (jj + j0) * self.nx + (ii + i0)

    def pad_keep(self, via_r):
        """Cells where a via of radius via_r would touch an SMD pad (any net): no via-in-pad."""
        key = round(via_r, 3)
        if key not in self._pad_keep:
            m = np.zeros((self.ny, self.nx), bool)
            for it in self.items:
                if it.kind != "poly" or it.virtual or len(it.layers) != 1 or it.layers[0] not in (F, B):
                    continue
                D = via_r + 0.05
                x1, y1, x2, y2 = it.bbox()
                j0, j1, i0, i1 = self._window(x1 - D, y1 - D, x2 + D, y2 + D)
                X, Y = np.meshgrid(self.xs[i0:i1], self.ys[j0:j1])
                m[j0:j1, i0:i1] |= it.dist(X, Y) < D
            self._pad_keep[key] = m
        return self._pad_keep[key]

    # ---- routing -------------------------------------------------------------------------------------------
    def route_net(self, net, width=None, plane=False, name=None, attract=None, rip=True):
        """Join every island of `net`; with plane=True each small island drops its own via to In1.
        `attract` names a route (e.g. "SP_A") this net should run beside."""
        self.opts[net] = dict(width=width, plane=plane, name=name, attract=attract)
        for spec in self.explicit.get(net, []):
            if not any(r.get("spec") is spec for r in self.routes.values()):
                self._connect_spec(spec, rip=rip)
        isl = self.islands(net)
        if plane:
            small = [i for i in isl if not any(z.IsOnLayer(pcbnew.In1_Cu) for z in i["zones"]) and i["pads"]]
            ok = True
            for s in small:
                big = [i for i in self.islands(net) if any(z.IsOnLayer(pcbnew.In1_Cu) for z in i["zones"])]
                # each pad gets its own via: the targets are the plane and the net's pours, not other drops
                big = [dict(b, vias=[], tracks=[], rvias=[], rtracks=[]) for b in big]
                if not self.connect(net, s, big, width=width, plane=True, name=name, rip=rip):
                    ok = False
                    self._fail(net, self._isl_name(s))
            return ok
        tried = set()
        while len(isl) > 1:
            isl.sort(key=lambda i: (len(i["zones"]) > 0, len(i["pads"]) + len(i["vias"]) + len(i["tracks"])))
            cand = [i for i in isl if self._isl_key(i) not in tried]
            if not cand:
                self._fail(net, [self._isl_name(i) for i in isl])
                return False
            src = cand[0]
            tgts = [i for i in isl if i is not src]
            if not self.connect(net, src, tgts, width=width, name=name, attract=attract, rip=rip):
                tried.add(self._isl_key(src))
            isl = self.islands(net)
        return True

    def connect_pads(self, net, src_pads, tgt_pads, width=None, name=None, attract=None, rip=True):
        """An explicit pad-to-pad connection (e.g. a gate-drive return to the FET sources); kept
        as a spec so a rip-up re-routes it the same way."""
        spec = dict(net=net, src=src_pads, tgt=tgt_pads, width=width, name=name, attract=attract)
        self.explicit.setdefault(net, []).append(spec)
        return self._connect_spec(spec, rip=rip)

    def _connect_spec(self, spec, rip=True):
        pick = lambda lst: [p for ref, num in lst for p in self.fps[ref].Pads() if p.GetNumber() == num]  # noqa: E731
        net = spec["net"]
        base = self._initial_islands(net)
        ids = lambda pads: {i for i, b in enumerate(base) for p in b["pads"] for q in pads if p.m_Uuid.AsString() == q.m_Uuid.AsString()}  # noqa: E731,E501
        sp, tp = pick(spec["src"]), pick(spec["tgt"])
        src = {"pads": sp, "vias": [], "tracks": [], "zones": [], "ids": ids(sp)}
        tgt = {"pads": tp, "vias": [], "tracks": [], "zones": [], "ids": ids(tp)}
        ok = self.connect(net, src, [tgt], width=spec["width"], name=spec["name"], attract=spec["attract"],
                          neck_pads=False, rip=rip, spec=spec)
        if not ok:
            self._fail(net, (spec["src"], spec["tgt"]))
        return ok

    def _fail(self, net, what):
        self.failed.append((self.netinfo[net]["name"], what, self.why))
        self.log(f"  failed: {self.failed[-1]}")

    @staticmethod
    def _isl_key(i):
        return frozenset(p.m_Uuid.AsString() for p in i["pads"])

    @staticmethod
    def _isl_name(i):
        return ",".join(sorted(f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}" for p in i["pads"]))[:80]

    def paths(self, name):
        """Segments of the routes recorded under `name` (for pair attraction)."""
        return [(L, p1, p2) for r in self.routes.values() if r.get("name") == name for L, p1, p2, _ in r["segs"]]

    def drain(self, rounds=12):
        """Re-route nets whose routes were ripped up, until none is left (bounded)."""
        for _ in range(rounds):
            if not self.pending:
                return
            todo, self.pending = self.pending, []
            for net in dict.fromkeys(todo):
                if self.nfail.get(net, 0) >= 3:
                    continue                          # failed three times: leave it for the report
                o = self.opts.get(net, {})
                before = len(self.failed)
                self.route_net(net, width=o.get("width"), plane=o.get("plane", False), name=o.get("name"),
                               attract=o.get("attract"), rip=self.rips.get(net, 0) < MAX_RIPS)
                if len(self.failed) > before:
                    self.nfail[net] = self.nfail.get(net, 0) + 1

    def connect(self, net, src, tgts, width=None, plane=False, attract=None, name=None, neck_pads=True, rip=True,
                spec=None):
        info = self.netinfo[net]
        w = width or info["width"]
        hw = w / 2
        clear = info["clear"]
        via_r = info["via"] / 2
        hard, soft = self.profile(clear, hw)
        neck = self.profile(clear, NECK_W / 2) if w > 0.25 + 1e-6 else None   # 0.25 fits a 0.5 mm pitch, 0.3 does not
        vhard, vsoft = self.profile(clear, via_r)
        NK = self.NK
        Xg, Yg = np.meshgrid(self.xs, self.ys)

        # neck zones (wide classes narrow down near small pads) and pour-escape zones
        neck_zone = None
        if neck is not None and neck_pads:
            neck_zone = np.zeros((self.ny, self.nx), bool)
        esc_zone = np.zeros((self.ny, self.nx), bool)
        for isl in [src] + list(tgts):
            for pad in isl["pads"]:
                cx, cy = self.P(pad.GetPosition())
                sz = pad.GetSize(pad.GetPrincipalLayer())
                big = max(mm(sz.x), mm(sz.y)) / 2
                rr = big + POUR_ESCAPE
                j0, j1, i0, i1 = self._window(cx - rr, cy - rr, cx + rr, cy + rr)
                esc_zone[j0:j1, i0:i1] |= np.hypot(Xg[j0:j1, i0:i1] - cx, Yg[j0:j1, i0:i1] - cy) < rr
                if neck_zone is not None and min(mm(sz.x), mm(sz.y)) < w + 0.1:
                    rr = big + NECK_R
                    j0, j1, i0, i1 = self._window(cx - rr, cy - rr, cx + rr, cy + rr)
                    neck_zone[j0:j1, i0:i1] |= np.hypot(Xg[j0:j1, i0:i1] - cx, Yg[j0:j1, i0:i1] - cy) < rr

        free = lambda o: (o == -1) | (o == net)  # noqa: E731
        pas_h, pas_s, wide = {}, {}, {}
        for L in ROUTE_LAYERS:
            wall = (self.zone_net[L] != -1) & (self.zone_net[L] != net) & ~esc_zone
            fh = free(hard[L]) & ~wall
            fs = free(soft[L])
            if neck_zone is not None:
                nh, ns = neck
                nz = neck_zone & ~wall
                fh2 = fh | (nz & free(nh[L]))
                fs2 = (fh & fs) | (nz & free(nh[L]) & free(ns[L]))
                wide[L] = fh & fs
                pas_h[L] = fh2.ravel().tobytes()
                pas_s[L] = (fh2 & ~fs2).ravel().tobytes()     # passable only by ripping
            else:
                wide[L] = fh & fs
                pas_h[L] = fh.ravel().tobytes()
                pas_s[L] = (fh & ~fs).ravel().tobytes()
        vh = np.ones((self.ny, self.nx), bool)
        vs = np.ones((self.ny, self.nx), bool)
        for L in KLAYER:
            vh &= free(vhard[L])
            vs &= free(vsoft[L])
        vh &= ~self.pad_keep(via_r)
        drill_r = info["drill"] / 2
        holes = [(it.geom[0], it.geom[1]) for it in self.items if it.kind == "circ" and len(it.layers) >= 3]
        holes += [((x, y), self.netinfo[r["net"]]["drill"] / 2) for r in self.routes.values() for x, y in r["vias"]]
        for (hx, hy), hr in holes:
            if hr > 0.6:                      # mounting holes and big pads are covered by the copper rasters
                continue
            D = drill_r + hr + HOLE_GAP + MARGIN
            j0, j1, i0, i1 = self._window(hx - D, hy - D, hx + D, hy + D)
            vh[j0:j1, i0:i1] &= np.hypot(Xg[j0:j1, i0:i1] - hx, Yg[j0:j1, i0:i1] - hy) >= D
        for x1, y1, x2, y2 in self.via_keepouts:
            j0, j1, i0, i1 = self._window(x1 - via_r, y1 - via_r, x2 + via_r, y2 + via_r)
            vh[j0:j1, i0:i1] = False
        for L in (F, B):
            vh &= ~((self.zone_net[L] != -1) & (self.zone_net[L] != net))
        via_pen = np.zeros((self.ny, self.nx), np.float32)
        zi = (self.zone_net[IN2] != -1) & (self.zone_net[IN2] != net)
        via_pen[zi & (self.zone_kind[IN2] == 2)] = 0.4
        via_pen[zi & (self.zone_kind[IN2] == 1)] = 3.0
        via_h = vh.ravel().tobytes()
        via_s = (vh & ~vs).ravel().tobytes()
        via_pen = via_pen.ravel()
        pour = {L: ((self.zone_net[L] != -1) & (self.zone_net[L] != net)).ravel().tobytes() for L in ROUTE_LAYERS}
        attr = None
        apath = self.paths(attract) if attract else []
        if apath:
            attr = {}
            for L in ROUTE_LAYERS:
                m = np.zeros((self.ny, self.nx), bool)
                for (La, p1, p2) in apath:
                    if La != L:
                        continue
                    j0, j1, i0, i1 = self._window(min(p1[0], p2[0]) - 0.8, min(p1[1], p2[1]) - 0.8,
                                                  max(p1[0], p2[0]) + 0.8, max(p1[1], p2[1]) + 0.8)
                    m[j0:j1, i0:i1] |= seg_dist(Xg[j0:j1, i0:i1], Yg[j0:j1, i0:i1], *p1, *p2) < 0.75
                attr[L] = m.ravel().tobytes()

        # targets (with the island each cell belongs to) and sources
        tisl = {L: np.full(NK, -1, np.int16) for L in KLAYER}
        anchors = []
        for ti, isl in enumerate(tgts):
            for pad in isl["pads"]:
                for L in self.pad_layers(pad):
                    tisl[L][self.pad_mask(pad, L)] = ti
                anchors.append(self.P(pad.GetPosition()))
            for (x, y) in isl["vias"]:
                k = self.cell(x, y)
                for L in ROUTE_LAYERS:
                    tisl[L][k] = ti
                anchors.append((x, y))
            for (L, a, bb) in isl["tracks"]:
                n = max(1, int(math.hypot(bb[0] - a[0], bb[1] - a[1]) / PITCH))
                for s in range(n + 1):
                    tisl[L][self.cell(a[0] + (bb[0] - a[0]) * s / n, a[1] + (bb[1] - a[1]) * s / n)] = ti
                anchors += [a, bb]
            for z in isl["zones"]:
                for kl in z.GetLayerSet().CuStack():
                    if kl in LIDX:
                        L = LIDX[kl]
                        tisl[L][self.zone_deep(L, net)] = ti
                bbx = z.GetBoundingBox()
                anchors.append(("box", mm(bbx.GetLeft()) - self.ox, mm(bbx.GetTop()) - self.oy,
                                mm(bbx.GetRight()) - self.ox, mm(bbx.GetBottom()) - self.oy))
        trec = {}                                     # (layer, cell) -> route id, for route geometry
        for ti, isl in enumerate(tgts):
            for rid, x, y in isl.get("rvias", ()):
                k = self.cell(x, y)
                for L in ROUTE_LAYERS:
                    tisl[L][k] = ti
                    trec[(L, k)] = rid
                anchors.append((x, y))
            for rid, L, a, bb in isl.get("rtracks", ()):
                n = max(1, int(math.hypot(bb[0] - a[0], bb[1] - a[1]) / PITCH))
                for s_ in range(n + 1):
                    k = self.cell(a[0] + (bb[0] - a[0]) * s_ / n, a[1] + (bb[1] - a[1]) * s_ / n)
                    tisl[L][k] = ti
                    trec[(L, k)] = rid
                anchors += [a, bb]
        if plane:
            tisl[IN1][:] = 0
        tbytes = {L: (tisl[L] >= 0).tobytes() for L in KLAYER}

        srcs = []
        for pad in src["pads"]:
            kc = self.cell(*self.P(pad.GetPosition()))
            for L in self.pad_layers(pad):
                ks = [int(k) for k in self.pad_mask(pad, L) if pas_h[L][int(k)] and not pas_s[L][int(k)]]
                srcs += [(L, k) for k in (ks or [kc])]
        for (x, y) in src["vias"]:
            k = self.cell(x, y)
            srcs += [(L, k) for L in ROUTE_LAYERS]
        for (L, a, bb) in src["tracks"]:
            n = max(1, int(math.hypot(bb[0] - a[0], bb[1] - a[1]) / PITCH))
            for s in range(n + 1):
                srcs.append((L, self.cell(a[0] + (bb[0] - a[0]) * s / n, a[1] + (bb[1] - a[1]) * s / n)))
        srec = {}
        for rid, x, y in src.get("rvias", ()):
            k = self.cell(x, y)
            for L in ROUTE_LAYERS:
                srcs.append((L, k))
                srec[(L, k)] = rid
        for rid, L, a, bb in src.get("rtracks", ()):
            n = max(1, int(math.hypot(bb[0] - a[0], bb[1] - a[1]) / PITCH))
            for s_ in range(n + 1):
                k = self.cell(a[0] + (bb[0] - a[0]) * s_ / n, a[1] + (bb[1] - a[1]) * s_ / n)
                srcs.append((L, k))
                srec[(L, k)] = rid
        if not srcs:
            self.why = "no sources"
            return False

        args = (srcs, tbytes, pas_h, via_h, via_pen, pour, attr, anchors, plane)
        free_now = {L: np.frombuffer(pas_h[L], bool) & ~np.frombuffer(pas_s[L], bool) for L in ROUTE_LAYERS}
        vias_now = np.frombuffer(via_h, bool) & ~np.frombuffer(via_s, bool)
        # a cheap A* first; if it runs out, a flood fill decides between "try harder" and "rip up"
        path = self._astar(*args, soft=(pas_s, via_s, False, None), max_exp=300000)
        if path is None and self.why.startswith("search budget"):
            if self._reachable(srcs, tisl, free_now, vias_now, plane):
                path = self._astar(*args, soft=(pas_s, via_s, False, None), max_exp=1500000, weight=1.5)
            else:
                self.why = "unreachable without rip-up"
        ripped = set()
        if path is None and rip:
            why = self.why
            # negotiated: crossing a net costs more the more often it has been ripped already
            costs = {}
            for L in ROUTE_LAYERS:
                o = soft[L].ravel()
                c = np.full(o.shape, RIP_COST * 3.0, np.float32)
                for n_, k_ in self.rips.items():
                    c[o == n_] = RIP_COST * (1.0 + k_)
                c[(o >= 0) & ~np.isin(o, list(self.rips.keys()) or [-9])] = RIP_COST
                costs[L] = c.tolist()
            path = self._astar(*args, soft=(pas_s, via_s, True, costs), max_exp=1500000, weight=2.0)
            if path is None:
                self.why = f"{why}; with rip-up: {self.why}"
            else:
                ripped = self._conflicts(net, path, clear, hw, via_r)
        if path is None:
            return False
        end = path[-1]
        ti = int(tisl[end[0]][end[1]])
        joins = set(src.get("ids", ())) | set(tgts[ti].get("ids", ())) if ti >= 0 else set(src.get("ids", ()))
        if not joins:
            joins = set()
        deps = {d for d in (srec.get(tuple(path[0])), trec.get(tuple(path[-1]))) if d is not None}
        for rid in ripped:
            self._rip(rid)
        if any(d not in self.routes for d in deps):
            return False                              # it leaned on a route that a rip-up just removed
        self._commit(net, path, w, wide, info, name, joins, spec, deps)
        return True

    def _reachable(self, srcs, tisl, free, vias, plane):
        """Flood fill over passable cells (8-connected, through legal via spots between layers):
        can any target be reached at all? Cheap compared with an A* that has to exhaust its budget."""
        H, W = self.ny, self.nx
        fr = {L: free[L].reshape(H, W) for L in ROUTE_LAYERS}
        vi = vias.reshape(H, W)
        tg = {L: (tisl[L] >= 0).reshape(H, W) for L in ROUTE_LAYERS}
        reach = {L: np.zeros((H, W), bool) for L in ROUTE_LAYERS}
        for L, k in srcs:
            if L in reach:
                reach[L].flat[k] = True
        for L in ROUTE_LAYERS:
            reach[L] |= False
        for _ in range(4000):
            changed = False
            for L in ROUTE_LAYERS:
                r = reach[L]
                g = r.copy()
                g[1:, :] |= r[:-1, :]; g[:-1, :] |= r[1:, :]
                g[:, 1:] |= g[:, :-1]; g[:, :-1] |= g[:, 1:]
                g &= fr[L] | r
                if (g & tg[L]).any():
                    return True
                if plane and (g & vi).any():
                    return True
                if (g != r).any():
                    reach[L] = g
                    changed = True
            # vias: a reached legal via spot reaches every layer there
            v = vi & (reach[F] | reach[IN2] | reach[B])
            for L in ROUTE_LAYERS:
                nv = v & fr[L] & ~reach[L]
                if nv.any():
                    reach[L] |= nv
                    changed = True
            if not changed:
                return False
        return True

    def _astar(self, srcs, tb, passable, via_ok, via_pen, pour, attr, anchors, plane, soft=None,
               max_exp=1500000, weight=1.0):
        nx, NK = self.nx, self.NK
        g = PITCH
        steps = [(dx + dy * nx, dx, dy, g * (math.sqrt(2) if dx and dy else 1.0)) for dx, dy in DIRS]
        soft_cells, soft_vias, soft_on, soft_cost = soft
        pts, boxes = [], []
        for a in anchors:
            if a[0] == "box":
                boxes.append(a[1:])
            else:
                pts.append(a)
        xs0, ys0 = -self.w2, -self.h2
        hcache = {}

        def h(k):
            v = hcache.get(k)
            if v is not None:
                return v
            x = xs0 + (k % nx) * g
            y = ys0 + (k // nx) * g
            best = 1e9
            for ax, ay in pts:
                dx, dy = abs(x - ax), abs(y - ay)
                d = max(dx, dy) + 0.41421356 * min(dx, dy)
                if d < best:
                    best = d
            for bx1, by1, bx2, by2 in boxes:
                dx = max(bx1 - x, 0.0, x - bx2)
                dy = max(by1 - y, 0.0, y - by2)
                d = max(dx, dy) + 0.41421356 * min(dx, dy)
                if d < best:
                    best = d
            if best == 1e9:
                best = 0.0
            hcache[k] = best
            return best

        best_g, parent, heap = {}, {}, []
        for L, k in srcs:
            key = (L * NK + k) * 9 + 8
            if best_g.get(key, 1e18) > 0:
                best_g[key] = 0.0
                parent[key] = None
                heapq.heappush(heap, (weight * h(k), 0.0, key))
        exp = 0
        while heap:
            f, gc, key = heapq.heappop(heap)
            if gc > best_g.get(key, 1e18):
                continue
            d = key % 9
            s = key // 9
            L, k = divmod(s, NK)
            if tb[L][k]:
                return self._unwind(parent, key)
            exp += 1
            if exp > max_exp:
                self.why = f"search budget spent ({exp} expansions)"
                return None
            x = k % nx
            if L != IN1:
                pas = passable[L]
                sc = soft_cells[L]
                scc = soft_cost[L] if soft_on else None
                pr = pour[L]
                at = attr[L] if attr else None
                lm = LAYER_MUL[L]
                for nd, (dk, dx, dy, ln) in enumerate(steps):
                    if d != 8:
                        dd = abs(nd - d)
                        dd = min(dd, 8 - dd)
                        if dd > 2:
                            continue
                        tc = TURN_COST[dd]
                    else:
                        tc = 0.0
                    nxx = x + dx
                    if nxx < 0 or nxx >= nx:
                        continue
                    nk = k + dk
                    if nk < 0 or nk >= NK or not pas[nk]:
                        continue
                    c = ln * lm
                    if sc[nk]:
                        if not soft_on:
                            continue
                        c += scc[nk] * ln
                    if pr[nk]:
                        c *= POUR_COST
                    if at is not None and at[nk]:
                        c *= 0.5
                    ng = gc + c + tc
                    nkey = (L * NK + nk) * 9 + nd
                    if ng < best_g.get(nkey, 1e18):
                        best_g[nkey] = ng
                        parent[nkey] = key
                        heapq.heappush(heap, (ng + weight * h(nk), ng, nkey))
            if (d != 8 or parent[key] is None) and via_ok[k]:
                if soft_vias[k] and not soft_on:
                    continue
                vc = VIA_COST + float(via_pen[k]) + (RIP_COST * 2 if soft_vias[k] else 0.0)
                for L2 in KLAYER:
                    if L2 == L or (L2 == IN1 and not plane):
                        continue
                    if L2 != IN1 and (not passable[L2][k] or (soft_cells[L2][k] and not soft_on)):
                        continue
                    ng = gc + vc
                    nkey = (L2 * NK + k) * 9 + 8
                    if ng < best_g.get(nkey, 1e18):
                        best_g[nkey] = ng
                        parent[nkey] = key
                        heapq.heappush(heap, (ng + weight * h(k), ng, nkey))
        self.why = f"frontier empty after {exp} expansions"
        return None

    def _unwind(self, parent, key):
        out = []
        NK = self.NK
        while key is not None:
            s = key // 9
            out.append(divmod(s, NK))
            key = parent[key]
        out.reverse()
        return out

    def _conflicts(self, net, path, clear, hw, via_r):
        """Route ids whose copper the (soft-mode) path comes too close to."""
        hit = set()
        cells = {}
        prev = None
        for L, k in path:
            if prev is not None and prev[1] == k and prev[0] != L:
                cells.setdefault(("via", k), via_r)
            elif L != IN1:
                cells.setdefault((L, k), hw)
            prev = (L, k)
        for (L, k), r in cells.items():
            x, y = self.xy(k)
            for rid, rec in self.routes.items():
                if rec["net"] == net or rid in hit:
                    continue
                for it in rec["items"]:
                    if L != "via" and L not in it.layers:
                        continue
                    D = max(clear, it.clear) + r + MARGIN
                    x1, y1, x2, y2 = it.bbox()
                    if x < x1 - D or x > x2 + D or y < y1 - D or y > y2 + D:
                        continue
                    if float(it.dist(np.array(x), np.array(y))) < D:
                        hit.add(rid)
                        break
        return hit

    def _rip(self, rid):
        """Rip up a route and every route that ends on it (they would dangle), transitively."""
        if rid not in self.routes:
            return
        gone = {rid}
        while True:
            more = {k for k, r in self.routes.items() if k not in gone and r.get("deps", set()) & gone}
            if not more:
                break
            gone |= more
        items, nets = [], []
        for k in gone:
            r = self.routes.pop(k)
            items += r["items"]
            nets.append(r["net"])
        self._repaint_soft(items)
        for net in dict.fromkeys(nets):
            self.rips[net] = self.rips.get(net, 0) + 1
            self.pending.append(net)
        self.log(f"  ripped {', '.join(self.netinfo[n]['name'] for n in dict.fromkeys(nets))} ({len(gone)} routes)")

    def _commit(self, net, path, w, wide, info, name, joins, spec, deps=()):
        """Path of (layer, cell) → a route record (tracks, vias) painted into the soft rasters."""
        segs, vias = [], []
        run = [path[0]]
        for a in path[1:]:
            if a[0] != run[-1][0]:
                if a[1] == run[-1][1]:
                    vias.append(a[1])
                if len(run) > 1 and run[0][0] != IN1:
                    segs += self._run_to_segs(run, w, wide)
                run = [a]
            else:
                run.append(a)
        if len(run) > 1 and run[0][0] != IN1:
            segs += self._run_to_segs(run, w, wide)
        vxy = [self.xy(k) for k in dict.fromkeys(vias)]
        self._rid += 1
        items = [Item(net, (L,), "seg", (p1, p2), info["clear"], ww / 2, route=self._rid) for L, p1, p2, ww in segs]
        items += [Item(net, tuple(KLAYER), "circ", ((x, y), info["via"] / 2), info["clear"], route=self._rid)
                  for x, y in vxy]
        self.routes[self._rid] = dict(net=net, segs=segs, vias=vxy, items=items, name=name, joins=joins, spec=spec,
                                      deps=set(deps))
        for key, sr in self.soft.items():
            for it in items:
                self._paint(it, key, sr)

    def _run_to_segs(self, run, w, wide):
        """Cells on one layer → straight segments (collinear merged), neck width where needed."""
        L = run[0][0]
        wf = wide[L].ravel()
        pts = [self.xy(k) for _, k in run]
        narrow = [not wf[k] for _, k in run]
        out = []
        start = 0
        for i in range(1, len(pts)):
            last = i == len(pts) - 1
            dir_change = False
            if not last:
                d1 = (round((pts[i][0] - pts[i - 1][0]) / PITCH), round((pts[i][1] - pts[i - 1][1]) / PITCH))
                d2 = (round((pts[i + 1][0] - pts[i][0]) / PITCH), round((pts[i + 1][1] - pts[i][1]) / PITCH))
                dir_change = d1 != d2
            width_change = (not last) and (narrow[i] or narrow[i + 1]) != (narrow[i - 1] or narrow[i])
            if last or dir_change or width_change:
                ww = min(NECK_W if any(narrow[start:i + 1]) else w, w)
                out.append((L, pts[start], pts[i], ww))
                start = i
        return out

    # ---- output -------------------------------------------------------------------------------------------
    def finalize(self):
        """Write every route to the board as locked tracks and vias; returns (tracks, vias)."""
        nt = nv = 0
        V = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x + self.ox), pcbnew.FromMM(y + self.oy))  # noqa: E731
        for rec in self.routes.values():
            net, info = rec["net"], self.netinfo[rec["net"]]
            for L, p1, p2, ww in rec["segs"]:
                t = pcbnew.PCB_TRACK(self.b)
                t.SetStart(V(*p1)); t.SetEnd(V(*p2)); t.SetWidth(pcbnew.FromMM(ww))
                t.SetLayer(KLAYER[L]); t.SetNetCode(net); t.SetLocked(True)
                self.b.Add(t)
                nt += 1
            for x, y in rec["vias"]:
                v = pcbnew.PCB_VIA(self.b)
                v.SetPosition(V(x, y)); v.SetViaType(pcbnew.VIATYPE_THROUGH)
                v.SetWidth(pcbnew.FromMM(info["via"])); v.SetDrill(pcbnew.FromMM(info["drill"]))
                v.SetNetCode(net); v.SetLocked(True)
                self.b.Add(v)
                nv += 1
        return nt, nv
