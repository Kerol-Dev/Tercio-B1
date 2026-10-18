"""Brand type on the silkscreen: IBM Plex outlines (hardware/lib/fonts, SIL OFL) as filled polygons.

KiCad's own TrueType text needs the font installed on every machine that opens the board; this reads
the WOFF files the website uses (TrueType outlines inside), flattens the glyphs and hands the board
plain polygons, so the gerbers carry exactly these shapes. Stdlib only (runs in KiCad's Python).
"""
from __future__ import annotations

import pathlib
import struct
import zlib

FONTS = pathlib.Path(__file__).resolve().parent.parent / "lib" / "fonts"
FACES = {
    "display": "ibm-plex-sans-condensed-latin-600-normal.woff",
    "display-bold": "ibm-plex-sans-condensed-latin-700-normal.woff",
    "mono": "ibm-plex-mono-latin-600-normal.woff",
}


class Font:
    def __init__(self, path: pathlib.Path):
        d = path.read_bytes()
        if d[:4] != b"wOFF":
            raise ValueError(f"{path}: not a WOFF file")
        n = struct.unpack(">H", d[12:14])[0]
        self.t = {}
        for i in range(n):
            tag, off, clen, olen, _ = struct.unpack(">4sIIII", d[44 + i * 20:64 + i * 20])
            raw = d[off:off + clen]
            self.t[tag.decode()] = zlib.decompress(raw) if clen < olen else raw
        head = self.t["head"]
        self.upm = struct.unpack(">H", head[18:20])[0]
        self.long_loca = struct.unpack(">h", head[50:52])[0] == 1
        self.nglyphs = struct.unpack(">H", self.t["maxp"][4:6])[0]
        self.nhm = struct.unpack(">H", self.t["hhea"][34:36])[0]
        os2 = self.t["OS/2"]
        self.cap = struct.unpack(">h", os2[88:90])[0] if len(os2) >= 90 else int(self.upm * 0.7)
        self.cmap = self._cmap()
        self._cache = {}

    # ---- tables ------------------------------------------------------------------------------------
    def _cmap(self):
        c = self.t["cmap"]
        n = struct.unpack(">H", c[2:4])[0]
        best = None
        for i in range(n):
            pid, eid, off = struct.unpack(">HHI", c[4 + i * 8:12 + i * 8])
            fmt = struct.unpack(">H", c[off:off + 2])[0]
            if fmt == 4 and (pid, eid) in ((3, 1), (0, 3), (0, 4)):
                best = off
        if best is None:
            raise ValueError("no format-4 cmap")
        o = best
        segx2 = struct.unpack(">H", c[o + 6:o + 8])[0]
        seg = segx2 // 2
        ends = struct.unpack(f">{seg}H", c[o + 14:o + 14 + segx2])
        starts = struct.unpack(f">{seg}H", c[o + 16 + segx2:o + 16 + 2 * segx2])
        deltas = struct.unpack(f">{seg}h", c[o + 16 + 2 * segx2:o + 16 + 3 * segx2])
        ro = o + 16 + 3 * segx2
        ranges = struct.unpack(f">{seg}H", c[ro:ro + segx2])
        out = {}
        for k in range(seg):
            for ch in range(starts[k], ends[k] + 1):
                if ch == 0xFFFF:
                    continue
                if ranges[k] == 0:
                    g = (ch + deltas[k]) & 0xFFFF
                else:
                    a = ro + k * 2 + ranges[k] + (ch - starts[k]) * 2
                    g = struct.unpack(">H", c[a:a + 2])[0]
                    if g:
                        g = (g + deltas[k]) & 0xFFFF
                if g:
                    out[ch] = g
        return out

    def advance(self, g):
        hm = self.t["hmtx"]
        i = min(g, self.nhm - 1)
        return struct.unpack(">H", hm[i * 4:i * 4 + 2])[0]

    def _loc(self, g):
        lo = self.t["loca"]
        if self.long_loca:
            a, b = struct.unpack(">II", lo[g * 4:g * 4 + 8])
        else:
            a, b = (2 * v for v in struct.unpack(">HH", lo[g * 2:g * 2 + 4]))
        return a, b

    # ---- glyph outlines (font units, y up) -----------------------------------------------------------
    def contours(self, g, steps=6):
        if g in self._cache:
            return self._cache[g]
        a, b = self._loc(g)
        gl = self.t["glyf"][a:b]
        out = []
        if gl:
            nc = struct.unpack(">h", gl[:2])[0]
            out = self._simple(gl, nc, steps) if nc >= 0 else self._composite(gl, steps)
        self._cache[g] = out
        return out

    def _simple(self, gl, nc, steps):
        p = 10
        ends = struct.unpack(f">{nc}H", gl[p:p + 2 * nc]); p += 2 * nc
        ilen = struct.unpack(">H", gl[p:p + 2])[0]; p += 2 + ilen
        npts = ends[-1] + 1 if nc else 0
        flags = []
        while len(flags) < npts:
            f = gl[p]; p += 1
            flags.append(f)
            if f & 8:
                r = gl[p]; p += 1
                flags += [f] * r
        xs, ys = [], []
        for coords, short, same in ((xs, 2, 16), (ys, 4, 32)):
            v = 0
            for f in flags:
                if f & short:
                    dv = gl[p]; p += 1
                    v += dv if f & same else -dv
                elif not f & same:
                    v += struct.unpack(">h", gl[p:p + 2])[0]; p += 2
                coords.append(v)
        out, s = [], 0
        for e in ends:
            pts = [(xs[i], ys[i], flags[i] & 1) for i in range(s, e + 1)]
            s = e + 1
            out.append(_flatten(pts, steps))
        return out

    def _composite(self, gl, steps):
        p, out = 10, []
        while True:
            fl, gi = struct.unpack(">HH", gl[p:p + 4]); p += 4
            if fl & 1:
                dx, dy = struct.unpack(">hh", gl[p:p + 4]); p += 4
            else:
                dx, dy = struct.unpack(">bb", gl[p:p + 2]); p += 2
            a = d_ = 1.0
            b = c = 0.0
            if fl & 8:
                a = d_ = struct.unpack(">h", gl[p:p + 2])[0] / 16384; p += 2
            elif fl & 0x40:
                a, d_ = (v / 16384 for v in struct.unpack(">hh", gl[p:p + 4])); p += 4
            elif fl & 0x80:
                a, b, c, d_ = (v / 16384 for v in struct.unpack(">hhhh", gl[p:p + 8])); p += 8
            for cont in self.contours(gi, steps):
                out.append([(a * x + c * y + dx, b * x + d_ * y + dy) for x, y in cont])
            if not fl & 0x20:
                break
        return out

    # ---- text -----------------------------------------------------------------------------------------
    def layout(self, s, cap_mm, tracking=0.0):
        """Contours in mm for string s: x from 0 rightward, y down, baseline at y = 0, cap height
        cap_mm. tracking: extra space between letters, in mm. Returns (contours, width)."""
        k = cap_mm / self.cap
        x, out = 0.0, []
        for i, ch in enumerate(s):
            g = self.cmap.get(ord(ch))
            if g is None:
                raise ValueError(f"glyph {ch!r} not in the font")
            for cont in self.contours(g):
                out.append([(x + px * k, -py * k) for px, py in cont])
            x += self.advance(g) * k + (tracking if i < len(s) - 1 else 0.0)
        return out, x


def _flatten(pts, steps):
    """TrueType quadratic contour (x, y, on) → polyline (closed, last point not repeated)."""
    n = len(pts)
    if not n:
        return []
    # start at an on-curve point (or the midpoint of two off-curve ones)
    k = next((i for i, q in enumerate(pts) if q[2]), None)
    if k is None:
        a, b = pts[0], pts[1]
        pts = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 1)] + pts[1:] + pts[:1]
        k = 0
    seq = pts[k:] + pts[:k]
    seq.append(seq[0])
    out = [(seq[0][0], seq[0][1])]
    prev = seq[0]
    i = 1
    while i < len(seq):
        q = seq[i]
        if q[2]:
            out.append((q[0], q[1]))
            prev = q
            i += 1
            continue
        nxt = seq[i + 1] if i + 1 < len(seq) else seq[0]
        end = nxt if nxt[2] else ((q[0] + nxt[0]) / 2, (q[1] + nxt[1]) / 2, 1)
        for s in range(1, steps + 1):
            t = s / steps
            u = 1 - t
            out.append((u * u * prev[0] + 2 * u * t * q[0] + t * t * end[0],
                        u * u * prev[1] + 2 * u * t * q[1] + t * t * end[1]))
        prev = end
        i += 1 if not nxt[2] else 2
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


_fonts = {}


def font(face="display"):
    if face not in _fonts:
        _fonts[face] = Font(FONTS / FACES[face])
    return _fonts[face]


def nest(contours):
    """Split contours into (outline, [holes]) groups by containment (even-odd nesting)."""
    def inside(pt, poly):
        x, y = pt
        c = False
        for i in range(len(poly)):
            x1, y1 = poly[i]
            x2, y2 = poly[i - 1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
        return c

    def area(poly):
        return abs(sum(poly[i - 1][0] * poly[i][1] - poly[i][0] * poly[i - 1][1] for i in range(len(poly)))) / 2

    cs = [c for c in contours if len(c) >= 3]
    depth = [sum(1 for j, o in enumerate(cs) if j != i and inside(c[0], o)) for i, c in enumerate(cs)]
    groups = []
    for i, c in enumerate(cs):
        if depth[i] % 2 == 0:
            groups.append((c, []))
    for i, c in enumerate(cs):
        if depth[i] % 2 == 1:
            owners = [g for g in groups if inside(c[0], g[0])]
            if owners:
                min(owners, key=lambda g: area(g[0]))[1].append(c)
    return groups
