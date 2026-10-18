"""Routing problem → files for gen/fastroute.py. Runs in KiCad's Python.

gen/router.Router supplies the geometry: exact clearance ("hard") rasters per routing profile, escape
corridors, zones, pad cells and the islands each net starts from. This module turns the routing
plan (b1/routing.units) into flat arrays the compiled router can take:

  problem.npz   hard owner rasters per profile, zones, via blocks, island / pad cell lists
  problem.json  grid, layers, profiles and the units (net, width, profiles, attraction, islands)
"""
from __future__ import annotations

import json
import math

import numpy as np
import pcbnew

from .router import (IN1, IN2, KLAYER, LIDX, MARGIN, NECK_R, NECK_W, PITCH, POUR_ESCAPE, ROUTE_LAYERS, F, B,
                     Router, mm)

HOLE_GAP = 0.25


def export(board, classes, patterns, units_fn, npz_path, json_path, holes=(), escape=None, via_keepouts=(),
           via_in_pad=True, log=print):
    r = Router(board, classes, holes=holes, escape=escape, via_keepouts=via_keepouts, patterns=patterns,
               log=lambda m: None)
    N = r.NK
    NL = len(KLAYER)
    profiles: dict[tuple, int] = {}
    arrays: dict[str, np.ndarray] = {}

    def prof(clear, hw):
        key = (round(clear, 3), round(hw, 3))
        if key not in profiles:
            profiles[key] = len(profiles)
        return profiles[key]

    def cells_of_pad(pad):
        out = []
        for L in r.pad_layers(pad):
            out += [L * N + int(k) for k in r.pad_mask(pad, L)]
        return out

    def seg_cells(L, a, b):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / PITCH))
        return [L * N + r.cell(a[0] + (b[0] - a[0]) * s / n, a[1] + (b[1] - a[1]) * s / n) for s in range(n + 1)]

    deep_keys = {}

    def deep(L, net):
        key = f"deep_{L}_{net}"
        if key not in deep_keys:
            arrays[key] = np.packbits(r.zone_deep(L, net).astype(np.uint8))
            deep_keys[key] = True
        return key

    def island_export(isl, ui, ii):
        cells = []
        for pad in isl["pads"]:
            cells += cells_of_pad(pad)
        for (x, y) in isl["vias"]:
            k = r.cell(x, y)
            cells += [L * N + k for L in ROUTE_LAYERS]
        for (L, a, b) in isl["tracks"]:
            cells += seg_cells(L, a, b)
        key = f"u{ui}_i{ii}"
        arrays[key] = np.array(sorted(set(cells)), dtype=np.int64)
        zones = []
        for z in isl["zones"]:
            for kl in z.GetLayerSet().CuStack():
                if kl in LIDX and LIDX[kl] in ROUTE_LAYERS:
                    zones.append(deep(LIDX[kl], z.GetNetCode()))
        plane = any(z.IsOnLayer(pcbnew.In1_Cu) for z in isl["zones"])
        return dict(cells=key, zones=sorted(set(zones)), plane=plane, npads=len(isl["pads"]))

    def pad_rows(pads, w):
        """(cx, cy, escape radius, neck radius) in cells for the pads a unit starts or ends at."""
        rows = []
        for pad in pads:
            cx, cy = r.P(pad.GetPosition())
            sz = pad.GetSize(pad.GetPrincipalLayer())
            big = max(mm(sz.x), mm(sz.y)) / 2
            small = min(mm(sz.x), mm(sz.y)) < w + 0.1
            rows.append(((cx + r.w2) / PITCH, (cy + r.h2) / PITCH, (big + POUR_ESCAPE) / PITCH,
                         (big + NECK_R) / PITCH if small else 0.0))
        return rows

    units = []
    plan = units_fn(r)
    for ui, u in enumerate(plan):
        if u["net"] not in r.code:
            continue
        net = r.code[u["net"]]
        info = r.netinfo[net]
        w = u.get("width") or info["width"]
        clear = info["clear"]
        rec = dict(kind=u["kind"], net=net, net_name=u["net"], name=u.get("name"), attract=u.get("attract"),
                   pair=u.get("pair"),
                   width=w, clear=clear, via=info["via"], drill=info["drill"],
                   p_wide=prof(clear, w / 2), p_neck=prof(clear, NECK_W / 2) if w > 0.25 + 1e-6 else -1,
                   p_via=prof(clear, info["via"] / 2))
        if u["kind"] == "explicit":
            pick = lambda lst: [p for ref, num in lst for p in r.fps[ref].Pads() if p.GetNumber() == num]  # noqa: E731
            sp, tp = pick(u["src"]), pick(u["tgt"])
            joined = lambda i, pads: any(q.m_Uuid.AsString() == p.m_Uuid.AsString() for q in i["pads"] for p in pads)  # noqa: E731
            if any(joined(i, sp) and joined(i, tp) for i in r._initial_islands(net)):
                continue                  # already connected (routes re-applied from b1/routes.json)
            arrays[f"u{ui}_src"] = np.array(sorted({c for p in sp for c in cells_of_pad(p)}), dtype=np.int64)
            arrays[f"u{ui}_tgt"] = np.array(sorted({c for p in tp for c in cells_of_pad(p)}), dtype=np.int64)
            rec.update(src=f"u{ui}_src", tgt=f"u{ui}_tgt", pads=pad_rows(sp + tp, w))
        else:
            isl = r._initial_islands(net)
            if u["kind"] == "net" and len(isl) < 2:
                continue
            rec["islands"] = [island_export(i, ui, ii) for ii, i in enumerate(isl)]
            rec["island_pads"] = [pad_rows(i["pads"], w) for i in isl]
            if u["kind"] == "plane" and not any(i["plane"] for i in rec["islands"]):
                continue
        units.append(rec)

    # rasters: hard owners per profile, zones, via blocks per via profile
    P = len(profiles)
    hard = np.full((P, NL * N), -1, np.int16)
    for (clear, hw), pi in profiles.items():
        h, _ = r.profile(clear, hw)
        for L in KLAYER:
            hard[pi, L * N:(L + 1) * N] = h[L].ravel()
    arrays["hard"] = hard
    arrays["zone_net"] = np.concatenate([r.zone_net[L].ravel() for L in KLAYER]).astype(np.int16)
    arrays["zone_kind"] = np.concatenate([r.zone_kind[L].ravel() for L in KLAYER]).astype(np.int8)
    Xg, Yg = np.meshgrid(r.xs, r.ys)
    fixed_holes = [(it.geom[0], it.geom[1]) for it in r.items if it.kind == "circ" and len(it.layers) >= 3]
    vblocks = {}
    for u in units:
        key = f"vblock_{u['p_via']}_{u['drill']}"
        if key in vblocks:
            u["vblock"] = key
            continue
        via_r, drill_r = u["via"] / 2, u["drill"] / 2
        # via-in-pad (filled and capped, free on JLC's 6-layer boards): a via may sit in a pad of its own
        # net; the hard rasters still keep it clear of every other net's pads
        vb = np.zeros((r.ny, r.nx), bool) if via_in_pad else r.pad_keep(via_r).copy()
        for x1, y1, x2, y2 in via_keepouts:
            j0, j1, i0, i1 = r._window(x1 - via_r, y1 - via_r, x2 + via_r, y2 + via_r)
            vb[j0:j1, i0:i1] = True
        for (hx, hy), hr in fixed_holes:
            if hr > 0.6:
                continue
            D = drill_r + hr + HOLE_GAP + MARGIN
            j0, j1, i0, i1 = r._window(hx - D, hy - D, hx + D, hy + D)
            vb[j0:j1, i0:i1] |= np.hypot(Xg[j0:j1, i0:i1] - hx, Yg[j0:j1, i0:i1] - hy) < D
        arrays[key] = vb.ravel().astype(np.uint8)
        vblocks[key] = True
        u["vblock"] = key

    meta = dict(nx=r.nx, ny=r.ny, pitch=PITCH, x0=-r.w2, y0=-r.h2, layers=[board.GetLayerName(KLAYER[L]) for L in KLAYER],
                routable=[1 if L in ROUTE_LAYERS else 0 for L in KLAYER], plane_layer=IN1, in2=IN2, outer=[F, B],
                profiles=[dict(clear=k[0], hw=k[1]) for k, _ in sorted(profiles.items(), key=lambda kv: kv[1])],
                margin=MARGIN, hole_gap=HOLE_GAP, units=units,
                names={str(k): v["name"] for k, v in r.netinfo.items()})
    np.savez_compressed(npz_path, **arrays)
    json_path.write_text(json.dumps(meta))
    log(f"export: {len(units)} units, {P} profiles, {len(arrays)} arrays")
    return meta
