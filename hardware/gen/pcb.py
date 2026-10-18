"""Board engine: netlist -> .kicad_pcb with code-defined placement and copper.

Runs under KiCad's bundled Python (it needs `pcbnew`). Coordinates are local
millimetres with the board centre at (0, 0), x right, y down; `origin` shifts
them onto the KiCad page.

Footprints come from KiCad's libraries (or the project library), get the
reference, value, nets and the schematic path from the netlist KiCad exported,
so `kicad-cli pcb drc --schematic-parity` checks the board against the
schematic. Every footprint's courtyard is tracked per side; `auto()` searches
outward from an anchor for the nearest collision-free spot.
"""
from __future__ import annotations

import math
import pathlib

import pcbnew

from . import sexpr
from .sexpr import Sym, find, find_all

FP_ROOT = pathlib.Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")
LAYER = {"F.Cu": pcbnew.F_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu, "In3.Cu": pcbnew.In3_Cu,
         "In4.Cu": pcbnew.In4_Cu, "B.Cu": pcbnew.B_Cu}


def mm(v: float) -> int:
    return pcbnew.FromMM(v)


def tomm(v: int) -> float:
    return pcbnew.ToMM(v)


class Rect:
    __slots__ = ("x1", "y1", "x2", "y2", "ref")

    def __init__(self, x1, y1, x2, y2, ref=""):
        self.x1, self.y1, self.x2, self.y2, self.ref = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2), ref

    def hits(self, o: "Rect", gap=0.0) -> bool:
        return not (self.x2 + gap <= o.x1 or o.x2 + gap <= self.x1 or self.y2 + gap <= o.y1 or o.y2 + gap <= self.y1)

    def moved(self, dx, dy):
        return Rect(self.x1 + dx, self.y1 + dy, self.x2 + dx, self.y2 + dy, self.ref)


def rot_rect(r: Rect, deg: int, mirror: bool) -> Rect:
    """Courtyard box of a footprint at the origin after (optional) bottom-side mirror and rotation."""
    x1, y1, x2, y2 = r.x1, r.y1, r.x2, r.y2
    if mirror:
        x1, x2 = -x2, -x1
    pts = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
    a = math.radians(deg)
    c, s = round(math.cos(a), 6), round(math.sin(a), 6)
    # KiCad rotates counter-clockwise on screen (y down): (x, y) -> (x c + y s, -x s + y c)
    rp = [(x * c + y * s, -x * s + y * c) for x, y in pts]
    return Rect(min(p[0] for p in rp), min(p[1] for p in rp), max(p[0] for p in rp), max(p[1] for p in rp))


class Pcb:
    def __init__(self, netlist: pathlib.Path, project_lib: pathlib.Path, size=(46.0, 46.0), origin=(150.0, 100.0),
                 layers=4):
        self.ox, self.oy = origin
        self.w, self.h = size
        self.project_lib = project_lib
        self.board = pcbnew.BOARD()
        self.board.SetCopperLayerCount(layers)
        self.comps: dict[str, dict] = {}
        self.pin_net: dict[tuple, str] = {}
        self._read_netlist(netlist)
        self.nets = {}
        for name in sorted(set(self.pin_net.values())):
            ni = pcbnew.NETINFO_ITEM(self.board, name)
            self.board.Add(ni)
            self.nets[name] = ni
        self.fps: dict[str, pcbnew.FOOTPRINT] = {}
        self.side: dict[str, str] = {}
        self.taken = {"T": [], "B": []}
        self.keep = {"T": [], "B": []}  # Rect or (x, y, r) circles
        self._local_crtyd: dict[str, Rect] = {}
        self.failed: list[str] = []

    @classmethod
    def wrap(cls, board, origin=(150.0, 100.0), size=(46.0, 46.0)):
        """Engine view of an existing board (e.g. reloaded after routing) for zones, vias and tracks."""
        self = cls.__new__(cls)
        self.board, (self.ox, self.oy), (self.w, self.h) = board, origin, size
        nets = (board.FindNet(c) for c in range(1, board.GetNetCount()))
        self.nets = {str(n.GetNetname()): n for n in nets if n is not None and n.GetNetname()}
        self.fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
        return self

    # ---- netlist ---------------------------------------------------------------------------
    def _read_netlist(self, path):
        tree = sexpr.loads(path.read_text())
        for c in find_all(find(tree, "components"), "comp"):
            ref = find(c, "ref")[1]
            props = {find(p, "name")[1]: (find(p, "value")[1] if find(p, "value") else "") for p in find_all(c, "property")}
            sheet = find(find(c, "sheetpath"), "tstamps")[1]
            fields = {}
            for f in find_all(find(c, "fields"), "field"):
                fields[find(f, "name")[1]] = f[2] if len(f) > 2 else ""
            self.comps[ref] = {"value": find(c, "value")[1], "footprint": find(c, "footprint")[1], "fields": fields,
                               "path": f"{sheet}{find(c, 'tstamps')[1]}", "dnp": "dnp" in props,
                               "exclude_bom": "exclude_from_bom" in props}
        for n in find_all(find(tree, "nets"), "net"):
            name = find(n, "name")[1]
            for node in find_all(n, "node"):
                self.pin_net[(find(node, "ref")[1], find(node, "pin")[1])] = name

    def net(self, name):
        """Net by name; local nets may be given without their /Sheet/ prefix."""
        if name in self.nets:
            return self.nets[name]
        hits = [n for k, n in self.nets.items() if k.endswith("/" + name)]
        if len(hits) != 1:
            raise KeyError(f"net {name!r}: {len(hits)} matches")
        return hits[0]

    # ---- coordinates ---------------------------------------------------------------------------
    def V(self, x, y):
        return pcbnew.VECTOR2I(mm(self.ox + x), mm(self.oy + y))

    def L(self, v):
        return tomm(v.x) - self.ox, tomm(v.y) - self.oy

    # ---- footprints --------------------------------------------------------------------------------
    def _load(self, ref):
        c = self.comps[ref]
        lib, name = c["footprint"].split(":", 1)
        libdir = self.project_lib if lib == "Tercio_B1" else FP_ROOT / f"{lib}.pretty"
        fp = pcbnew.FootprintLoad(str(libdir), name)
        if fp is None:
            raise SystemExit(f"{ref}: footprint {c['footprint']} not found")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH(c["path"]))
        for pad in fp.Pads():
            net = self.pin_net.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(self.nets[net])
        for name in ("Datasheet", "Description", "LCSC", "MPN"):
            if name in c["fields"] or name in ("Datasheet", "Description"):
                fp.SetField(name, c["fields"].get(name, ""))
                fp.GetField(name).SetVisible(False)
        if c["dnp"]:
            fp.SetDNP(True)
        self.board.Add(fp)
        self.fps[ref] = fp
        # courtyard at the origin, top side, rotation 0
        fp.SetPosition(pcbnew.VECTOR2I(0, 0))
        self._local_crtyd[ref] = self._crtyd(fp, pcbnew.F_CrtYd, local=False)
        return fp

    def _crtyd(self, fp, layer, local=True) -> Rect:
        fp.BuildCourtyardCaches()
        poly = fp.GetCourtyard(layer)
        if poly.OutlineCount():
            box = poly.BBox()
        else:  # no courtyard: pads plus a small margin
            box = fp.GetBoundingBox(False)
        x1, y1 = tomm(box.GetX()), tomm(box.GetY())
        x2, y2 = x1 + tomm(box.GetWidth()), y1 + tomm(box.GetHeight())
        if local:
            x1, y1, x2, y2 = x1 - self.ox, y1 - self.oy, x2 - self.ox, y2 - self.oy
        return Rect(x1, y1, x2, y2, fp.GetReference())

    def is_tht(self, ref) -> bool:
        return any(p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) for p in self.fps[ref].Pads())

    def place(self, ref, x, y, rot=0, side="T"):
        fp = self.fps.get(ref) or self._load(ref)
        fp.SetPosition(self.V(x, y))
        if side == "B" and not fp.IsFlipped():
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        self.side[ref] = side
        box = self._crtyd(fp, pcbnew.B_CrtYd if side == "B" else pcbnew.F_CrtYd)
        self.taken[side].append(box)
        self._fanout_ring(fp, ref, side)
        if self.is_tht(ref):  # through-hole pads also occupy the other side
            other = "B" if side == "T" else "T"
            for p in fp.Pads():
                if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                    px, py = self.L(p.GetPosition())
                    r = max(tomm(p.GetSize().x), tomm(p.GetSize().y)) / 2 + 0.3
                    self.keep[other].append(Rect(px - r, py - r, px + r, py + r, ref))
        return fp

    FAN_RING = 1.0       # mm kept free of other parts around fine-pitch pads (their escapes need it)
    fan_rings: dict = {}  # per-reference overrides

    def _fanout_ring(self, fp, ref, side):
        pads = [q for q in fp.Pads() if q.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
        if len(pads) < 8:
            return
        pos = [self.L(q.GetPosition()) for q in pads]
        pitch = min((((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for i, a in enumerate(pos) for b in pos[i + 1:]),
                    default=9)
        if pitch > 0.65:
            return
        bb = None
        for q in pads:
            b = q.GetBoundingBox()
            x1, y1 = self.L(pcbnew.VECTOR2I(b.GetLeft(), b.GetTop()))
            x2, y2 = self.L(pcbnew.VECTOR2I(b.GetRight(), b.GetBottom()))
            bb = (x1, y1, x2, y2) if bb is None else (min(bb[0], x1), min(bb[1], y1), max(bb[2], x2), max(bb[3], y2))
        g = self.fan_rings.get(ref, self.FAN_RING)
        self.keep[side].append(Rect(bb[0] - g, bb[1] - g, bb[2] + g, bb[3] + g, f"fan-out {ref}"))

    def net_centroid(self, ref):
        """Centroid of the placed pads that share a net with `ref`'s first pad (for test points)."""
        fp = self.fps.get(ref) or self._load(ref)
        net = next(p.GetNetname() for p in fp.Pads())
        pts = [self.L(q.GetPosition()) for r, f in self.fps.items() if r != ref and r in self.side
               for q in f.Pads() if q.GetNetname() == net]
        if not pts:
            return (0.0, 0.0)
        return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))

    def pad_xy(self, ref, num):
        fp = self.fps[ref]
        pad = fp.FindPadByNumber(str(num))
        return self.L(pad.GetPosition())

    def fits(self, r: Rect, side, gap=0.15, region: Rect | None = None, ignore=()) -> bool:
        m = 0.35  # copper/courtyard to board edge
        if r.x1 < -self.w / 2 + m or r.x2 > self.w / 2 - m or r.y1 < -self.h / 2 + m or r.y2 > self.h / 2 - m:
            return False
        if region and (r.x1 < region.x1 or r.x2 > region.x2 or r.y1 < region.y1 or r.y2 > region.y2):
            return False
        for o in self.taken[side]:
            if r.hits(o, gap):
                return False
        for k in self.keep[side]:
            if isinstance(k, Rect):
                if k.ref not in ignore and r.hits(k, 0.0):
                    return False
            else:
                cx, cy, rad = k
                nx, ny = min(max(cx, r.x1), r.x2), min(max(cy, r.y1), r.y2)
                if (nx - cx) ** 2 + (ny - cy) ** 2 < rad ** 2:
                    return False
        return True

    def auto(self, ref, near, side="T", rots=(0, 90), radius=16.0, step=0.25, region: Rect | None = None, gap=0.15,
             toward=None, grow=None):
        """Place `ref` at the free spot nearest to `near` (x, y) or (ref, pad). With `toward` (a point or
        (ref, pad), where the signal goes next) the spot is the free one closest to the straight line
        from `near` to `toward`, as near to `near` as possible: the part sits on its track's way out."""
        if isinstance(near[0], str):
            near = self.pad_xy(*near)
        if toward is not None and isinstance(toward[0], str):
            toward = self.pad_xy(*toward)
        if ref not in self.fps:
            self._load(ref)
        base = self._local_crtyd[ref]  # footprint-relative (measured with the footprint at 0, 0)
        if grow:                       # room kept free beside the part (left, top, right, bottom), e.g. a label
            base = Rect(base.x1 - grow[0], base.y1 - grow[1], base.x2 + grow[2], base.y2 + grow[3], ref)
        n = int(radius / step)
        cands = sorted(((i * step, j * step) for i in range(-n, n + 1) for j in range(-n, n + 1)
                        if (i * i + j * j) * step * step <= radius * radius), key=lambda d: d[0] ** 2 + d[1] ** 2)
        if toward is not None:
            L = math.hypot(toward[0] - near[0], toward[1] - near[1])
            tx, ty = toward[0] - near[0], toward[1] - near[1]

            def detour(d):          # extra length of near → part → toward over the straight line, plus distance
                r0 = math.hypot(*d)
                return 2.0 * (r0 + math.hypot(tx - d[0], ty - d[1]) - L) + 0.35 * r0
            cands.sort(key=detour)
        shapes = {r: rot_rect(base, r, side == "B") for r in rots}
        # holes (Tag-Connect guide pins, plated pins) must also be clear of parts on the other side
        fp = self.fps[ref]
        fp.SetPosition(pcbnew.VECTOR2I(0, 0)); fp.SetOrientationDegrees(0)
        holes = [(tomm(p.GetPosition().x), tomm(p.GetPosition().y), max(tomm(p.GetSize().x), tomm(p.GetSize().y)) / 2 + 0.5)
                 for p in fp.Pads() if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)]
        other = "B" if side == "T" else "T"

        def holes_clear(x, y, r):
            for hx, hy, hr in holes:
                hb = rot_rect(Rect(hx - hr, hy - hr, hx + hr, hy + hr), r, side == "B").moved(x, y)
                if any(hb.hits(o) for o in self.taken[other]):
                    return False
            return True

        for dx, dy in cands:
            x, y = round(near[0] + dx, 3), round(near[1] + dy, 3)
            for r in rots:
                if self.fits(shapes[r].moved(x, y), side, gap, region) and holes_clear(x, y, r):
                    fp = self.place(ref, x, y, r, side)
                    if grow:                   # the reserved room stays reserved for the parts placed later
                        self.taken[side].append(shapes[r].moved(x, y))
                    return fp
        self.failed.append(ref)
        print(f"  ! auto-place failed for {ref} near ({near[0]:.1f}, {near[1]:.1f}) on {side}")
        return self.place(ref, 0.0, 30.0, 0, side)  # parked below the board for inspection

    def find_free(self, side, w, h, region: Rect, step=0.5, near=(0.0, 0.0), gap=0.4, ignore=()):
        """Nearest free w × h box in `region` (for art), or None. `ignore`: keepout names art may cover."""
        best = None
        y = region.y1
        while y + h <= region.y2:
            x = region.x1
            while x + w <= region.x2:
                r = Rect(x, y, x + w, y + h)
                if self.fits(r, side, gap, ignore=ignore):
                    d = (x + w / 2 - near[0]) ** 2 + (y + h / 2 - near[1]) ** 2
                    if best is None or d < best[0]:
                        best = (d, r)
                x += step
            y += step
        return best[1] if best else None

    def keepout_circle(self, x, y, r, sides=("T", "B")):
        for s in sides:
            self.keep[s].append((x, y, r))

    def keepout_rect(self, x1, y1, x2, y2, sides=("T", "B"), name="keepout"):
        for s in sides:
            self.keep[s].append(Rect(x1, y1, x2, y2, name))

    # ---- board graphics -------------------------------------------------------------------------------
    def outline(self, radius=3.0, width=0.1):
        w2, h2, r = self.w / 2, self.h / 2, radius
        segs = [((-w2 + r, -h2), (w2 - r, -h2)), ((w2, -h2 + r), (w2, h2 - r)),
                ((w2 - r, h2), (-w2 + r, h2)), ((-w2, h2 - r), (-w2, -h2 + r))]
        for a, b in segs:
            s = pcbnew.PCB_SHAPE(self.board, pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(self.V(*a)); s.SetEnd(self.V(*b))
            s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(width))
            self.board.Add(s)
        for cx, cy, sx, sy in ((w2 - r, -h2 + r, w2 - r, -h2), (w2 - r, h2 - r, w2, h2 - r),
                               (-w2 + r, h2 - r, -w2 + r, h2), (-w2 + r, -h2 + r, -w2, -h2 + r)):
            a = pcbnew.PCB_SHAPE(self.board, pcbnew.SHAPE_T_ARC)
            a.SetCenter(self.V(cx, cy)); a.SetStart(self.V(sx, sy)); a.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(90, pcbnew.DEGREES_T), True)
            a.SetLayer(pcbnew.Edge_Cuts); a.SetWidth(mm(width))
            self.board.Add(a)

    def line(self, layer, a, b, width, net=None):
        s = pcbnew.PCB_SHAPE(self.board, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(self.V(*a)); s.SetEnd(self.V(*b)); s.SetLayer(layer); s.SetWidth(mm(width))
        self.board.Add(s)
        return s

    def circle(self, layer, c, r, width, fill=False):
        s = pcbnew.PCB_SHAPE(self.board, pcbnew.SHAPE_T_CIRCLE)
        s.SetCenter(self.V(*c)); s.SetEnd(self.V(c[0] + r, c[1])); s.SetLayer(layer); s.SetWidth(mm(width))
        s.SetFilled(fill)
        self.board.Add(s)
        return s

    def text(self, layer, s, at, size=1.0, thick=0.15, bold=False, justify="center", rot=0, mirror=False):
        t = pcbnew.PCB_TEXT(self.board)
        t.SetText(s); t.SetPosition(self.V(*at)); t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size))); t.SetTextThickness(mm(thick)); t.SetBold(bold)
        t.SetHorizJustify({"left": pcbnew.GR_TEXT_H_ALIGN_LEFT, "center": pcbnew.GR_TEXT_H_ALIGN_CENTER,
                           "right": pcbnew.GR_TEXT_H_ALIGN_RIGHT}[justify])
        t.SetTextAngleDegrees(rot)
        t.SetMirrored(mirror)
        self.board.Add(t)
        return t

    def poly(self, layer, outline, holes=(), width=0.0):
        """A filled polygon (with holes) in layout mm, e.g. silkscreen type and marks."""
        s = pcbnew.PCB_SHAPE(self.board, pcbnew.SHAPE_T_POLY)
        ps = pcbnew.SHAPE_POLY_SET()
        o = ps.NewOutline()
        for x, y in outline:
            ps.Append(mm(self.ox + float(x)), mm(self.oy + float(y)), o)
        for hole in holes:
            h = ps.NewHole(o)
            for x, y in hole:
                ps.Append(mm(self.ox + float(x)), mm(self.oy + float(y)), o, h)
        s.SetPolyShape(ps)
        s.SetFilled(True)
        s.SetWidth(mm(width))
        s.SetLayer(layer)
        self.board.Add(s)
        return s

    def zone(self, net, layer, pts, priority=0, clearance=0.25, min_width=0.25, connect="full", name=""):
        z = pcbnew.ZONE(self.board)
        z.SetLayer(LAYER[layer] if isinstance(layer, str) else layer)
        if net:
            z.SetNet(self.net(net))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(mm(self.ox + x), mm(self.oy + y))
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(mm(clearance))
        z.SetMinThickness(mm(min_width))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if connect == "full" else pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.3)); z.SetThermalReliefSpokeWidth(mm(0.4))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        if name:
            z.SetZoneName(name)
        self.board.Add(z)
        return z

    def rule_area(self, layer, pts, tracks=True, vias=False, name="keepout"):
        """Rule area (keepout) on one copper layer; by default it forbids tracks only."""
        z = pcbnew.ZONE(self.board)
        z.SetIsRuleArea(True)
        z.SetLayer(LAYER[layer] if isinstance(layer, str) else layer)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(mm(self.ox + x), mm(self.oy + y))
        z.SetDoNotAllowTracks(tracks); z.SetDoNotAllowVias(vias); z.SetDoNotAllowPads(False)
        z.SetDoNotAllowZoneFills(False); z.SetDoNotAllowFootprints(False)
        z.SetZoneName(name)
        self.board.Add(z)
        return z

    def via(self, net, at, drill=0.3, size=0.6):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(self.V(*at)); v.SetDrill(mm(drill)); v.SetWidth(mm(size))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetNet(self.net(net))
        self.board.Add(v)
        return v

    def track(self, net, layer, pts, width):
        for a, b in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(self.board)
            t.SetStart(self.V(*a)); t.SetEnd(self.V(*b)); t.SetWidth(mm(width))
            t.SetLayer(LAYER[layer]); t.SetNet(self.net(net))
            self.board.Add(t)

    def fill_zones(self):
        self.board.BuildConnectivity()
        pcbnew.ZONE_FILLER(self.board).Fill(self.board.Zones())

    def save(self, path: pathlib.Path):
        self.board.SetFileName(str(path))
        pcbnew.SaveBoard(str(path), self.board)
