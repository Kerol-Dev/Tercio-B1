#!/usr/bin/env python3
"""Negotiated-congestion grid router (PathFinder) compiled with Numba.

Reads the routing problem written by gen/route_export.py (KiCad's Python cannot run Numba), routes
every unit, and writes plain tracks and vias as JSON for layout.py to put on the board.

    python fastroute.py problem.npz problem.json routes-out.json

How it works
- Grid of 0.05 mm, layers as exported (In1 is the GND plane: vias only). A* over (layer, cell) with
  turn and via costs; legality comes from the exported exact clearance rasters ("hard": pads, holes,
  escape corridors, board edge), so DRC passes by construction.
- Routes are painted into per-profile occupancy grids as clearance capsules (same distance rule as
  the hard rasters). PathFinder: in every round each net rips up its own routes and routes again
  against the others' occupancy (present-congestion cost) plus a history cost that grows on cells
  that were fought over. Rounds repeat until no route overlaps another.
- Foreign power pours are walls except around the unit's own pads; wide nets neck down near small
  pads; GND islands drop to the In1 plane; pairs are attracted to their partner's route.
"""
from __future__ import annotations

import json
import math
import sys
import time

import numpy as np
from numba import njit

DX = np.array([1, 1, 0, -1, -1, -1, 0, 1], np.int64)
DY = np.array([0, 1, 1, 1, 0, -1, -1, -1], np.int64)
VIA_COST = 0.6                    # cheap enough that nets dive to the inner layers early
POUR_COST = 4.0
T45, T90 = 0.12, 0.5
ATTRACT_R = 0.75
MAX_ROUNDS = int(__import__("os").environ.get("FASTROUTE_ROUNDS", "60"))
RETRY_ROUNDS = int(__import__("os").environ.get("FASTROUTE_RETRY_ROUNDS", "12"))
PASSES = int(__import__("os").environ.get("FASTROUTE_PASSES", "4"))
PRES0, PRES_GROW, HIST_STEP = 0.5, 1.6, 0.8
PRES_MAX, HIST_MAX = 50.0, 10.0
WEIGHT = 1.3                      # weighted A*: a little optimality for far fewer expansions
MAX_EXP = 4_000_000
BIG_EXP = 20_000_000
HEAP_CAP = 40_000_000


# ---- heap ---------------------------------------------------------------------------------------------
@njit(cache=True, inline="always")
def hpush(hk, hv, n, k, v):
    i = n
    hk[i] = k
    hv[i] = v
    while i > 0:
        p = (i - 1) >> 1
        if hk[p] <= hk[i]:
            break
        hk[p], hk[i] = hk[i], hk[p]
        hv[p], hv[i] = hv[i], hv[p]
        i = p
    return n + 1


@njit(cache=True, inline="always")
def hpop(hk, hv, n):
    k, v = hk[0], hv[0]
    n -= 1
    hk[0] = hk[n]
    hv[0] = hv[n]
    i = 0
    while True:
        l = 2 * i + 1
        if l >= n:
            break
        m = l
        if l + 1 < n and hk[l + 1] < hk[l]:
            m = l + 1
        if hk[i] <= hk[m]:
            break
        hk[i], hk[m] = hk[m], hk[i]
        hv[i], hv[m] = hv[m], hv[i]
        i = m
    return k, v, n


# ---- geometry helpers --------------------------------------------------------------------------------------
@njit(cache=True, inline="always")
def near(pads, col, x, y):
    for i in range(pads.shape[0]):
        r = pads[i, col]
        if r > 0.0:
            dx = x - pads[i, 0]
            dy = y - pads[i, 1]
            if dx * dx + dy * dy < r * r:
                return True
    return False


@njit(cache=True, inline="always")
def cell_kind(idx, x, y, net, hard, pw, pn, zone_net, pads):
    """0 blocked, 1 wide, 2 neck; negative = inside a foreign pour near own pads (escape)."""
    ow = hard[pw, idx]
    k = 0
    if ow == -1 or ow == net:
        k = 1
    elif pn >= 0:
        on = hard[pn, idx]
        if (on == -1 or on == net) and near(pads, 3, x, y):
            k = 2
    if k == 0:
        return 0
    zn = zone_net[idx]
    if zn != -1 and zn != net:
        if near(pads, 2, x, y):
            return -k
        return 0
    return k


# ---- A* ---------------------------------------------------------------------------------------------------
@njit(cache=True)
def astar(nx, N, NL, routable, plane_layer, in2, outer, srcs, tmark, tval, plane,
          hard, pw, pn, pv, vblock, zone_net, zone_kind, pads,
          occ, vhole, hist, pres, net, attr, aval, use_attr, own_vias, via_sp,
          bx0, by0, bx1, by1, pitch, layer_mul, g, par, dirs, kinds, stamp, sval,
          hk, hv, max_exp, path_out, kind_out, weight, strict, apen):
    n = 0
    for si in range(srcs.shape[0]):
        s = srcs[si]
        L = s // N
        if routable[L] == 0:
            continue
        c = s % N
        k = cell_kind(s, c % nx, c // nx, net, hard, pw, pn, zone_net, pads)
        if k == 0:
            continue
        stamp[s] = sval
        g[s] = 0.0
        par[s] = -1
        dirs[s] = 8
        kinds[s] = abs(k)
        if n >= hk.shape[0]:
            return 0
        n = hpush(hk, hv, n, 0.0, s)
    if n == 0:
        return -1
    exp = 0
    goal = -1
    while n > 0:
        f, s, n = hpop(hk, hv, n)
        L = s // N
        c = s % N
        gs = g[s]
        x = c % nx
        y = c // nx
        dx_ = max(bx0 - x, 0, x - bx1)
        dy_ = max(by0 - y, 0, y - by1)
        hh = (max(dx_, dy_) + 0.41421356 * min(dx_, dy_)) * pitch * weight
        if f > gs + hh + 1e-4:
            continue
        if tmark[s] == tval:
            goal = s
            break
        exp += 1
        if exp > max_exp:
            return -2
        d = dirs[s]
        if routable[L] == 1:
            lm = layer_mul[L]
            for nd in range(8):
                tc = 0.0
                if d != 8:
                    dd = abs(nd - d)
                    if dd > 4:
                        dd = 8 - dd
                    if dd > 2:
                        continue
                    if dd == 1:
                        tc = T45
                    elif dd == 2:
                        tc = T90
                xx = x + DX[nd]
                yy = y + DY[nd]
                if xx < 0 or xx >= nx or yy < 0 or yy >= N // nx:
                    continue
                cc = yy * nx + xx
                t = L * N + cc
                k = cell_kind(t, xx, yy, net, hard, pw, pn, zone_net, pads)
                if k == 0:
                    continue
                ln = pitch * (1.41421356 if nd % 2 == 1 else 1.0)
                p = pw if abs(k) == 1 else pn
                o = occ[p, t]
                if strict and o > 0:
                    continue
                mult = (1.0 + hist[t]) * (1.0 + pres * o)
                if k < 0:
                    mult *= POUR_COST
                if use_attr:
                    if attr[t] == aval:
                        mult *= 0.5
                    else:
                        mult *= apen          # >1 for pairs that should not part (Kelvin, gate loop)
                ng = gs + ln * lm * mult + tc
                if stamp[t] != sval or ng < g[t]:
                    stamp[t] = sval
                    g[t] = ng
                    par[t] = s
                    dirs[t] = nd
                    kinds[t] = abs(k)
                    dxh = max(bx0 - xx, 0, xx - bx1)
                    dyh = max(by0 - yy, 0, yy - by1)
                    h2 = (max(dxh, dyh) + 0.41421356 * min(dxh, dyh)) * pitch * weight
                    if n >= hk.shape[0]:
                        return -3
                    n = hpush(hk, hv, n, ng + h2, t)
        # via (through), not right after another via
        if (d != 8 or par[s] == -1) and vblock[c] == 0:
            okv = True
            occs = 0
            for LL in range(NL):
                ov = hard[pv, LL * N + c]
                if ov != -1 and ov != net:
                    okv = False
                    break
                occs += occ[pv, LL * N + c]
            if okv:
                for oi in range(outer.shape[0]):
                    zn = zone_net[outer[oi] * N + c]
                    if zn != -1 and zn != net:
                        okv = False
            existing = False
            if okv:
                for vi in range(own_vias.shape[0]):
                    oc = own_vias[vi]
                    if oc == c:
                        existing = True
                        break
                    ddx = (oc % nx) - x
                    ddy = (oc // nx) - y
                    if ddx * ddx + ddy * ddy < via_sp * via_sp:
                        okv = False
                        break
            if okv and strict and (occs > 0 or vhole[c] > 0):
                okv = False
            if okv:
                vc = 0.0
                if not existing:
                    vc = VIA_COST + pres * (occs + vhole[c]) + hist[c]
                    for LL in range(NL):                  # through foreign inner planes / pours
                        if routable[LL] == 1 and LL != outer[0] and LL != outer[1]:
                            zi = zone_net[LL * N + c]
                            if zi != -1 and zi != net:
                                vc += 0.4 if zone_kind[LL * N + c] == 2 else 3.0
                for L2 in range(NL):
                    if L2 == L:
                        continue
                    t = L2 * N + c
                    if L2 == plane_layer:
                        if plane:
                            stamp[t] = sval
                            g[t] = gs + vc
                            par[t] = s
                            dirs[t] = 8
                            kinds[t] = 3
                            goal = t
                            break
                        continue
                    if routable[L2] == 0:
                        continue
                    k = cell_kind(t, x, y, net, hard, pw, pn, zone_net, pads)
                    if k == 0:
                        continue
                    ng = gs + vc
                    if stamp[t] != sval or ng < g[t]:
                        stamp[t] = sval
                        g[t] = ng
                        par[t] = s
                        dirs[t] = 8
                        kinds[t] = abs(k)
                        if n >= hk.shape[0]:
                            return -3
                        n = hpush(hk, hv, n, ng + hh, t)
                if goal >= 0:
                    break
    if goal < 0:
        return -1
    m = 0
    s = goal
    while s != -1:
        path_out[m] = s
        kind_out[m] = kinds[s]
        m += 1
        s = par[s]
        if m >= path_out.shape[0]:
            return -4
    # reverse
    for i in range(m // 2):
        path_out[i], path_out[m - 1 - i] = path_out[m - 1 - i], path_out[i]
        kind_out[i], kind_out[m - 1 - i] = kind_out[m - 1 - i], kind_out[i]
    return m


# ---- occupancy ----------------------------------------------------------------------------------------------
@njit(cache=True)
def paint_capsule(arr, base, nx, ny, ax, ay, bx, by, R, mark, mval, sign):
    """Add sign to arr[base + cell] for cells within R (cells) of segment a–b (once per mval)."""
    x0 = int(math.floor(min(ax, bx) - R)) - 1
    x1 = int(math.ceil(max(ax, bx) + R)) + 1
    y0 = int(math.floor(min(ay, by) - R)) - 1
    y1 = int(math.ceil(max(ay, by) + R)) + 1
    vx = bx - ax
    vy = by - ay
    l2 = vx * vx + vy * vy
    R2 = R * R
    for y in range(max(y0, 0), min(y1, ny - 1) + 1):
        for x in range(max(x0, 0), min(x1, nx - 1) + 1):
            t = 0.0
            if l2 > 0:
                t = ((x - ax) * vx + (y - ay) * vy) / l2
                t = min(max(t, 0.0), 1.0)
            px = ax + t * vx - x
            py = ay + t * vy - y
            if px * px + py * py < R2:
                i = base + y * nx + x
                if mark[i] != mval:
                    mark[i] = mval
                    arr[i] += sign


@njit(cache=True)
def paint_path(path, kinds, m, nx, ny, N, NL, plane_layer, hw_w, hw_n, via_r, uclear, sign,
               occ, prof_clear, prof_hw, pitch, margin, mark, mval, vhole, vh_r, vmark):
    """Paint (sign=+1) or remove (sign=-1) one route in every profile's occupancy grid."""
    P = occ.shape[0]
    for p in range(P):
        mval += 1
        i = 0
        while i < m:
            s = path[i]
            L = s // N
            c = s % N
            if i > 0 and path[i - 1] % N == c and path[i - 1] // N != L:      # via here
                R = (max(prof_clear[p], uclear) + prof_hw[p] + via_r + margin) / pitch
                for LL in range(NL):
                    paint_capsule(occ[p], LL * N, nx, ny, c % nx, c // nx, c % nx, c // nx, R, mark, mval, sign)
                i += 1
                continue
            if L == plane_layer:
                i += 1
                continue
            # a straight run on one layer with one width
            j = i
            dx0 = 0
            dy0 = 0
            while j + 1 < m:
                s2 = path[j + 1]
                if s2 // N != L or kinds[j + 1] != kinds[i]:
                    break
                ddx = (s2 % N) % nx - (path[j] % N) % nx
                ddy = (s2 % N) // nx - (path[j] % N) // nx
                if j > i and (ddx != dx0 or ddy != dy0):
                    break
                dx0 = ddx
                dy0 = ddy
                j += 1
            hw = hw_n if kinds[i] == 2 else hw_w
            R = (max(prof_clear[p], uclear) + prof_hw[p] + hw + margin) / pitch
            a = path[i] % N
            b = path[j] % N
            paint_capsule(occ[p], L * N, nx, ny, a % nx, a // nx, b % nx, b // nx, R, mark, mval, sign)
            i = j if j > i else i + 1
    # via holes (drill spacing between nets)
    mval += 1
    for i in range(1, m):
        s = path[i]
        c = s % N
        if path[i - 1] % N == c and path[i - 1] // N != s // N:
            paint_capsule(vhole, 0, nx, ny, c % nx, c // nx, c % nx, c // nx, vh_r / pitch, vmark, mval, sign)
    return mval


@njit(cache=True)
def overused(path, kinds, m, N, NL, plane_layer, pw, pn, pv, occ, vhole, hist, step, cap):
    bad = 0
    for i in range(m):
        s = path[i]
        L = s // N
        c = s % N
        if i > 0 and path[i - 1] % N == c and path[i - 1] // N != L:
            hit = vhole[c] > 0
            for LL in range(NL):
                if occ[pv, LL * N + c] > 0:
                    hit = True
            if hit:
                bad += 1
                for LL in range(NL):
                    hist[LL * N + c] = min(hist[LL * N + c] + step, cap)
            continue
        if L == plane_layer:
            continue
        p = pn if kinds[i] == 2 and pn >= 0 else pw
        if occ[p, s] > 0:
            bad += 1
            hist[s] = min(hist[s] + step, cap)
    return bad


@njit(cache=True)
def mark_disk(path, m, N, nx, ny, R, arr, aval):
    for i in range(m):
        s = path[i]
        L = s // N
        c = s % N
        cx = c % nx
        cy = c // nx
        r = int(R) + 1
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= R * R:
                    x = cx + dx
                    y = cy + dy
                    if 0 <= x < nx and 0 <= y < ny:
                        arr[L * N + y * nx + x] = aval


# ---- driver ---------------------------------------------------------------------------------------------------
class Solver:
    def __init__(self, npz, meta):
        self.m = meta
        self.nx, self.ny = meta["nx"], meta["ny"]
        self.N = self.nx * self.ny
        self.NL = len(meta["layers"])
        self.pitch = meta["pitch"]
        self.margin = meta["margin"]
        self.a = npz
        self.hard = npz["hard"]
        self.zone_net = npz["zone_net"]
        self.zone_kind = npz["zone_kind"]
        self.routable = np.array(meta["routable"], np.int64)
        self.plane_layer = meta["plane_layer"]
        self.in2 = meta["in2"]
        self.outer = np.array(meta["outer"], np.int64)
        self.layer_mul = np.array([1.0 if i in meta["outer"] else (1.1 if r else 0.0) for i, r in enumerate(meta["routable"])],
                                  np.float64)
        self.prof_clear = np.array([p["clear"] for p in meta["profiles"]], np.float64)
        self.prof_hw = np.array([p["hw"] for p in meta["profiles"]], np.float64)
        P, NL, N = len(meta["profiles"]), self.NL, self.N
        self.occ = np.zeros((P, NL * N), np.int16)
        self.vhole = np.zeros(N, np.int16)
        self.hist = np.zeros(NL * N, np.float32)
        self.g = np.zeros(NL * N, np.float32)
        self.par = np.zeros(NL * N, np.int64)
        self.dirs = np.zeros(NL * N, np.int8)
        self.kinds = np.zeros(NL * N, np.int8)
        self.stamp = np.zeros(NL * N, np.int32)
        self.tmark = np.zeros(NL * N, np.int32)
        self.amark = np.zeros(NL * N, np.int32)
        self.mark = np.zeros(NL * N, np.int32)
        self.vmark = np.zeros(N, np.int32)
        self.hk = np.zeros(HEAP_CAP, np.float64)
        self.hv = np.zeros(HEAP_CAP, np.int64)
        self.path = np.zeros(400_000, np.int64)
        self.pkind = np.zeros(400_000, np.int8)
        self.sval = 0
        self.tval = 0
        self.aval = 0
        self.mval = 0
        self.deep = {}
        self.max_drill_r = max((u["drill"] for u in meta["units"]), default=0.35) / 2
        # units grouped by net (in plan order)
        self.groups = {}
        for ui, u in enumerate(meta["units"]):
            self.groups.setdefault(u["net"], []).append(ui)
        self.routes = {}          # net -> list of (unit index, path array, kinds array)
        self.failed = {}

    def deep_cells(self, key):
        if key not in self.deep:
            _, L, _net = key.split("_")
            bits = np.unpackbits(self.a[key])[: self.N].astype(bool)
            self.deep[key] = np.flatnonzero(bits).astype(np.int64) + int(L) * self.N
        return self.deep[key]

    def pads_array(self, rows):
        return np.array(rows, np.float64).reshape(-1, 4) if rows else np.zeros((0, 4), np.float64)

    def bbox_of(self, cells):
        c = cells % self.N
        xs, ys = c % self.nx, c // self.nx
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    def run_astar(self, u, srcs, tgt_cells, plane, pads, own_vias, attract_path, pres, weight=WEIGHT, budget=MAX_EXP):
        strict = pres < 0                     # legalisation: other nets' copper is a wall
        pres = abs(pres)
        self.sval += 1
        self.tval += 1
        if tgt_cells.size:
            self.tmark[tgt_cells] = self.tval
            bx0, by0, bx1, by1 = self.bbox_of(tgt_cells)
        else:
            bx0, by0, bx1, by1 = -10**9, -10**9, 10**9, 10**9
        if plane:
            bx0, by0, bx1, by1 = -10**9, -10**9, 10**9, 10**9
        use_attr = attract_path is not None and attract_path.size > 0
        if use_attr:
            self.aval += 1
            mark_disk(attract_path, attract_path.size, self.N, self.nx, self.ny, ATTRACT_R / self.pitch,
                      self.amark, self.aval)
        via_sp = (u["drill"] + self.m["hole_gap"] + self.margin) / self.pitch     # drill to drill, same net
        for attempt in range(2):
            m = astar(self.nx, self.N, self.NL, self.routable, self.plane_layer, self.in2, self.outer, srcs, self.tmark,
                      self.tval, plane, self.hard, u["p_wide"], u["p_neck"], u["p_via"], self.a[u["vblock"]],
                      self.zone_net, self.zone_kind, pads, self.occ, self.vhole, self.hist, pres, u["net"],
                      self.amark, self.aval, use_attr, own_vias, via_sp,
                      bx0, by0, bx1, by1, self.pitch, self.layer_mul, self.g, self.par, self.dirs, self.kinds,
                      self.stamp, self.sval, self.hk, self.hv, budget, self.path, self.pkind, weight, strict,
                      float(u.get("pair") or 1.0))
            if m != -2 or budget >= BIG_EXP:
                break
            # out of budget (high congestion costs flatten the heuristic): one more try, much wider
            budget = BIG_EXP
            self.sval += 1
        if m <= 0:
            return None
        return self.path[:m].copy(), self.pkind[:m].copy()

    def vias_of(self, path):
        N = self.N
        c = path % N
        same = (c[1:] == c[:-1]) & ((path[1:] // N) != (path[:-1] // N))
        return np.unique(c[1:][same])

    def route_unit(self, ui, pres, own, weight=WEIGHT, budget=MAX_EXP):
        """Route one unit; own = list of (path, kinds) already routed for this net in this round."""
        u = self.m["units"][ui]
        own_cells = np.concatenate([p for p, _ in own]) if own else np.zeros(0, np.int64)
        own_vias = np.unique(np.concatenate([self.vias_of(p) for p, _ in own])) if own else np.zeros(0, np.int64)
        attract = None
        if u.get("attract"):
            for net, lst in self.routes.items():
                for (uj, p, _) in lst:
                    if self.m["units"][uj].get("name") == u["attract"]:
                        attract = p if attract is None else np.concatenate([attract, p])
        out = []
        if u["kind"] == "explicit":
            pads = self.pads_array(u["pads"])
            r = self.run_astar(u, self.a[u["src"]], self.a[u["tgt"]], False, pads, own_vias, attract, pres, weight, budget)
            return ([r], 0) if r else ([], 1)
        isl = u["islands"]
        if u["kind"] == "plane":
            tgt = [self.deep_cells(z) for i in isl if i["plane"] for z in i["zones"]]
            tgt = np.concatenate(tgt) if tgt else np.zeros(0, np.int64)
            nf = 0
            for ii, i in enumerate(isl):
                if i["plane"] or i["npads"] == 0:
                    continue
                pads = self.pads_array(u["island_pads"][ii])
                ov = np.unique(np.concatenate([own_vias] + [self.vias_of(p) for p, _ in out])) if out else own_vias
                r = self.run_astar(u, self.a[i["cells"]], tgt, True, pads, ov, None, pres, weight, budget)
                if r:
                    out.append(r)
                else:
                    nf += 1
            return out, nf
        # tree: start from the island with zones (or the most pads), join the others nearest first
        order = sorted(range(len(isl)), key=lambda k: (-len(isl[k]["zones"]), -isl[k]["npads"]))
        tree = [self.a[isl[order[0]]["cells"]]] + [self.deep_cells(z) for z in isl[order[0]]["zones"]]
        # this net's routes from earlier units (an explicit loop, a gate return) join the tree only once
        # they touch it: a link between two islands is not a link to the rest of the net
        pending = [p for p, _ in own]

        def absorb():
            grown = True
            while grown and pending:
                grown = False
                tc = np.concatenate(tree)
                for p in list(pending):
                    if np.isin(p, tc).any():
                        tree.append(p)
                        pending.remove(p)
                        grown = True
        absorb()
        rest = order[1:]
        nf = 0
        while rest:
            tcells = np.concatenate(tree)
            tc = tcells % self.N
            tx, ty = (tc % self.nx).mean(), (tc // self.nx).mean()

            def dist(k):
                c = self.a[isl[k]["cells"]] % self.N
                return ((c % self.nx).mean() - tx) ** 2 + ((c // self.nx).mean() - ty) ** 2
            rest.sort(key=dist)
            k = rest.pop(0)
            pads = self.pads_array(u["island_pads"][k] + [row for kk in order for row in u["island_pads"][kk]])
            ov = np.unique(np.concatenate([own_vias] + [self.vias_of(p) for p, _ in out])) if out else own_vias
            r = self.run_astar(u, self.a[isl[k]["cells"]], tcells, False, pads, ov, attract, pres, weight, budget)
            if not r:
                nf += 1               # this island stays out; the others may still join the tree
                continue
            out.append(r)
            tree += [r[0], self.a[isl[k]["cells"]]] + [self.deep_cells(z) for z in isl[k]["zones"]]
            absorb()
        return out, nf

    def paint(self, ui, path, kinds, sign):
        u = self.m["units"][ui]
        self.mval = paint_path(path, kinds, path.size, self.nx, self.ny, self.N, self.NL, self.plane_layer,
                               u["width"] / 2, 0.1, u["via"] / 2, u["clear"], sign, self.occ, self.prof_clear,
                               self.prof_hw, self.pitch, self.margin, self.mark, self.mval, self.vhole,
                               u["drill"] / 2 + self.max_drill_r + self.m["hole_gap"] + self.margin, self.vmark)

    def route_net(self, net, pres, weight=WEIGHT, budget=MAX_EXP):
        for (ui, p, k) in self.routes.get(net, []):
            self.paint(ui, p, k, -1)
        own, lst, fails = [], [], 0
        for ui in self.groups[net]:
            rs, nf = self.route_unit(ui, pres, own, weight, budget)
            fails += nf
            if nf:
                self.failed[ui] = nf
            else:
                self.failed.pop(ui, None)
            for (p, k) in rs:
                lst.append((ui, p, k))
                own.append((p, k))
        self.routes[net] = lst
        for (ui, p, k) in lst:
            self.paint(ui, p, k, +1)
        return fails

    def contested(self):
        """Per net: cells where its routes overlap other nets' (history grows there)."""
        out = {}
        for net, lst in self.routes.items():
            for (ui, p, k) in lst:
                self.paint(ui, p, k, -1)
            b = 0
            for (ui, p, k) in lst:
                u = self.m["units"][ui]
                b += overused(p, k, p.size, self.N, self.NL, self.plane_layer, u["p_wide"], u["p_neck"],
                              u["p_via"], self.occ, self.vhole, self.hist, HIST_STEP, HIST_MAX)
            for (ui, p, k) in lst:
                self.paint(ui, p, k, +1)
            if b:
                out[net] = b
        return out

    def negotiate(self, todo, rounds, rnd0, t0, log):
        for rnd in range(rnd0, rnd0 + rounds):
            pres = min(PRES0 * PRES_GROW ** rnd, PRES_MAX)
            for net in todo:
                self.route_net(net, pres)
            bad = self.contested()
            fails = sum(self.failed.values())
            log(f"round {rnd + 1}: {len(todo)} nets routed, {sum(bad.values())} contested cells in {len(bad)} nets, "
                f"{fails} unrouted, {time.time() - t0:.1f} s")
            if not bad and not fails:
                break
            # after the first rounds only the nets still in conflict (or unrouted) are routed again
            failed_nets = {self.m["units"][ui]["net"] for ui in self.failed}
            # (every sixth round everyone moves again, so nets out of conflict can make room too)
            todo = [n for n in self.groups if n in bad or n in failed_nets] \
                if rnd >= 2 and (rnd + 1) % 6 else list(self.groups)
            if not bad and rnd > 4:
                break

    def legalise(self, order, t0, log):
        """Drop the least important net of every remaining conflict, then put the dropped nets back one
        by one (most important first) with other nets' copper as walls; what does not fit stays unrouted."""
        dropped = []
        while True:
            bad = self.contested()
            if not bad:
                break
            worst = max(bad, key=lambda n: order[n])
            for (ui, p, k) in self.routes.get(worst, []):
                self.paint(ui, p, k, -1)
            self.routes[worst] = []
            dropped.append(worst)
        for ui in list(self.failed):
            net = self.m["units"][ui]["net"]
            if net not in dropped:
                dropped.append(net)
        for net in sorted(set(dropped), key=lambda n: order[n]):
            self.route_net(net, -PRES_MAX, weight=1.5, budget=20_000_000)
        bad = self.contested()
        log(f"legalise: {len(set(dropped))} nets re-placed strictly, {sum(bad.values())} contested cells, "
            f"{sum(self.failed.values())} unrouted connections, {time.time() - t0:.1f} s")
        return sum(bad.values()), sum(self.failed.values())

    def _swap(self, nets, routes, failed):
        """Put `routes` / `failed` (saved per net) back for `nets`, repainting the rasters."""
        for n in nets:
            for (ui, p, k) in self.routes.get(n, []):
                self.paint(ui, p, k, -1)
        for n in nets:
            self.routes[n] = routes[n]
            for (ui, p, k) in routes[n]:
                self.paint(ui, p, k, +1)
            for ui in self.groups[n]:
                if ui in failed:
                    self.failed[ui] = failed[ui]
                else:
                    self.failed.pop(ui, None)

    def rescue(self, order, crit, t0, log):
        """Rip-up and reroute for the nets legalisation left unrouted: route the net softly to see whose
        copper is in its way, rip those nets, route the net strictly, then put the ripped nets back
        strictly. First only lower-priority victims, then any non-critical ones, then anyone. A move is kept only if
        fewer connections end up unrouted, so this always terminates."""
        for sweep in range(6):
            improved = False
            stuck = sorted({self.m["units"][ui]["net"] for ui in self.failed}, key=lambda n: order[n])
            for net in stuck:
                for level in (0, 1, 2):
                    if not any(self.m["units"][ui]["net"] == net for ui in self.failed):
                        break
                    before = sum(self.failed.values())
                    saved_r = {n: list(v) for n, v in self.routes.items()}
                    saved_f = dict(self.failed)
                    self.route_net(net, PRES_MAX, weight=1.2, budget=BIG_EXP)      # soft: overlaps allowed
                    bad = self.contested()
                    if level == 0:
                        victims = [n for n in bad if n != net and order[n] > order[net]]
                    elif level == 1:
                        victims = [n for n in bad if n != net and n not in crit]
                    else:                         # anyone in the way; kept only if the total improves
                        victims = [n for n in bad if n != net]
                    victims.sort(key=lambda n: order[n])
                    for v in victims:
                        for (ui, p, k) in self.routes.get(v, []):
                            self.paint(ui, p, k, -1)
                        self.routes[v] = []
                    self.route_net(net, -PRES_MAX, weight=1.5, budget=BIG_EXP)
                    for v in victims:
                        self.route_net(v, -PRES_MAX, weight=1.5, budget=BIG_EXP)
                    after = sum(self.failed.values())
                    if after < before and not self.contested():
                        log(f"rescue {self.m['names'].get(str(net), net)}: ripped {len(victims)} nets, "
                            f"unrouted {before} → {after}")
                        improved = True
                        break
                    self._swap([net] + victims, saved_r, saved_f)
            if not improved or not self.failed:
                break
        return sum(self.failed.values())

    def solve(self, log=print):
        """Negotiate, legalise; while connections are left, promote their nets ahead of the rest of the
        plan and negotiate again from where the board is (history kept). Keep the best pass."""
        t0 = time.time()
        plan = list(self.groups)
        first_plane = next((i for i, n in enumerate(plan)
                            if any(self.m["units"][ui]["kind"] == "plane" for ui in self.groups[n])), len(plan))
        crit = set(plan[:first_plane])
        promoted = []
        best = None
        rnd = 0
        for attempt in range(PASSES):
            rounds = MAX_ROUNDS if attempt == 0 else RETRY_ROUNDS
            todo = list(self.groups) if attempt == 0 else \
                [n for n in self.groups if any(self.m["units"][ui]["net"] == n for ui in self.failed)]
            self.negotiate(todo, rounds, rnd, t0, log)
            rnd += rounds
            # promoted nets move up within their tier only: the critical nets (Kelvin pairs, gate loops,
            # DRV supply: everything planned before the GND drops) always keep precedence over the rest
            seq = [n for n in promoted if n in crit] + [n for n in plan if n in crit and n not in promoted] + \
                [n for n in promoted if n not in crit] + [n for n in plan if n not in crit and n not in promoted]
            order = {n: i for i, n in enumerate(seq)}
            bad, fails = self.legalise(order, t0, log)
            if fails:
                fails = self.rescue(order, crit, t0, log)
                log(f"rescue: {fails} unrouted connections, {time.time() - t0:.1f} s")
            if best is None or fails < best[0]:
                best = (fails, {n: list(v) for n, v in self.routes.items()}, dict(self.failed))
            if not fails:
                break
            for ui in self.failed:
                n = self.m["units"][ui]["net"]
                if n not in promoted:
                    promoted.append(n)
            log(f"pass {attempt + 1}: {fails} unrouted; promoting {len(promoted)} nets and negotiating again")
        _, self.routes, self.failed = best
        return 0, best[0]

    # ---- output -----------------------------------------------------------------------------------------
    def to_routes(self):
        N, nx, pitch, x0, y0 = self.N, self.nx, self.pitch, self.m["x0"], self.m["y0"]
        names = self.m["layers"]
        out = {"tracks": [], "vias": [], "failed": []}
        xy = lambda c: [round(x0 + (c % nx) * pitch, 4), round(y0 + (c // nx) * pitch, 4)]  # noqa: E731
        for net, lst in self.routes.items():
            seen_vias = set()
            for (ui, path, kinds) in lst:
                u = self.m["units"][ui]
                i = 0
                m = path.size
                while i < m:
                    s = path[i]
                    L, c = divmod(int(s), N)
                    if i > 0 and int(path[i - 1]) % N == c and int(path[i - 1]) // N != L:
                        if c not in seen_vias:
                            seen_vias.add(c)
                            out["vias"].append({"net": u["net_name"], "at": xy(c), "size": u["via"], "drill": u["drill"]})
                        i += 1
                        continue
                    if not self.routable[L]:
                        i += 1
                        continue
                    j = i
                    d0 = None
                    while j + 1 < m and int(path[j + 1]) // N == L and kinds[j + 1] == kinds[i]:
                        a, b = int(path[j]) % N, int(path[j + 1]) % N
                        d = (b % nx - a % nx, b // nx - a // nx)
                        if d0 is not None and d != d0:
                            break
                        d0 = d
                        j += 1
                    if j > i:
                        w = 0.2 if kinds[i] == 2 else u["width"]
                        out["tracks"].append({"net": u["net_name"], "layer": names[L], "start": xy(int(path[i]) % N),
                                              "end": xy(int(path[j]) % N), "width": round(min(w, u["width"]), 4)})
                        i = j
                    else:
                        i += 1
        out["failed"] = [[self.m["units"][ui]["net_name"], n] for ui, n in self.failed.items()]
        return out


def main():
    npz_path, json_path, out_path = sys.argv[1:4]
    meta = json.loads(open(json_path).read())
    npz = dict(np.load(npz_path))
    s = Solver(npz, meta)
    bad, fails = s.solve(log=lambda m: print(m, flush=True))
    out = s.to_routes()
    out["contested"] = int(bad)
    open(out_path, "w").write(json.dumps(out))
    print(f"fastroute: {len(out['tracks'])} tracks, {len(out['vias'])} vias, {bad} contested cells, "
          f"failed units: {out['failed']}", flush=True)


if __name__ == "__main__":
    main()
