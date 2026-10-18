"""Schematic model -> KiCad 10 files (.kicad_sch per sheet, root sheet, .kicad_pro).

Every pin connection is drawn as a short wire stub ending in a net label,
a global label (net used on several sheets) or a power symbol. UUIDs are
derived from stable names, so regenerating an unchanged design gives
byte-identical files.
"""
from __future__ import annotations

import json
import pathlib
import uuid

from . import sexpr
from .model import NC, Part, Schematic, Sheet
from .sexpr import Sym, find, find_all, prop
from .symbols import direction, transform

VERSION = Sym("20260306")
_NS = uuid.UUID("6f1c2a52-7d0e-4c55-9a51-7465726369b1")  # "Tercio" namespace


def uid(*parts) -> str:
    return str(uuid.uuid5(_NS, "/".join(str(p) for p in parts)))


def r4(v: float) -> float:
    return round(v + 0.0, 4)


def font(size=1.27, bold=False, italic=False):
    f = [Sym("font"), [Sym("size"), size, size]]
    if bold:
        f.append([Sym("bold"), Sym("yes")])
    if italic:
        f.append([Sym("italic"), Sym("yes")])
    return f


def effects(justify=None, size=1.27, hide=False, bold=False, italic=False):
    e = [Sym("effects"), font(size, bold, italic)]
    if justify:
        e.append([Sym("justify")] + [Sym(j) for j in justify.split()])
    return e


def property_(name, value, x, y, angle=0, hide=False, justify=None, eff=None):
    p = [Sym("property"), name, value, [Sym("at"), r4(x), r4(y), angle]]
    if hide:
        p.append([Sym("hide"), Sym("yes")])
    p.append([Sym("show_name"), Sym("no")])
    p.append([Sym("do_not_autoplace"), Sym("no")])
    p.append(eff if eff is not None else effects(justify))
    return p


def label_angle(ox, oy) -> int:
    return {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(ox, oy)]


class SheetWriter:
    def __init__(self, sch: Schematic, sheet: Sheet | None, root_uuid: str, sheet_uuid: str | None, globals_: set[str]):
        self.sch = sch
        self.sheet = sheet
        self.root_uuid = root_uuid
        self.sheet_uuid = sheet_uuid
        self.globals = globals_
        self.items: list = []
        self.lib_ids: set[str] = set()
        self.pwr_count = 0
        self.path = f"/{root_uuid}/{sheet_uuid}" if sheet_uuid else f"/{root_uuid}"
        self.key = sheet.file if sheet else "root"

    # -- primitives -------------------------------------------------------------------
    def wire(self, x1, y1, x2, y2):
        self.items.append([Sym("wire"), [Sym("pts"), [Sym("xy"), r4(x1), r4(y1)], [Sym("xy"), r4(x2), r4(y2)]],
                           [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]],
                           [Sym("uuid"), uid(self.key, "wire", r4(x1), r4(y1), r4(x2), r4(y2))]])

    def no_connect(self, x, y):
        self.items.append([Sym("no_connect"), [Sym("at"), r4(x), r4(y)], [Sym("uuid"), uid(self.key, "nc", r4(x), r4(y))]])

    def label(self, net, x, y, angle, is_global):
        just = "right" if angle in (180, 270) else "left"
        if is_global:
            self.items.append([Sym("global_label"), net, [Sym("shape"), Sym("passive")],
                               [Sym("at"), r4(x), r4(y), angle], [Sym("fields_autoplaced"), Sym("yes")],
                               effects(just), [Sym("uuid"), uid(self.key, "glabel", net, r4(x), r4(y))],
                               [Sym("property"), "Intersheetrefs", "${INTERSHEET_REFS}", [Sym("at"), r4(x), r4(y), 0],
                                [Sym("hide"), Sym("yes")], effects(just)]])
        else:
            self.items.append([Sym("label"), net, [Sym("at"), r4(x), r4(y), angle], effects(just + " bottom"),
                               [Sym("uuid"), uid(self.key, "label", net, r4(x), r4(y))]])

    def text(self, x, y, s, size=1.27, bold=False):
        self.items.append([Sym("text"), s, [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), r4(x), r4(y), 0],
                           effects("left top", size=size, bold=bold), [Sym("uuid"), uid(self.key, "text", r4(x), r4(y), s[:40])]])

    def rect(self, x1, y1, x2, y2, title):
        self.items.append([Sym("rectangle"), [Sym("start"), r4(x1), r4(y1)], [Sym("end"), r4(x2), r4(y2)],
                           [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("dash")], [Sym("color"), 132, 132, 132, 1]],
                           [Sym("fill"), [Sym("type"), Sym("none")]], [Sym("uuid"), uid(self.key, "rect", r4(x1), r4(y1))]])
        if title:
            self.text(x1 + 1.27, y1 + 1.27, title, size=1.778, bold=True)

    # -- symbols ----------------------------------------------------------------------------
    def symbol_instance(self, lib_id, ref, value, x, y, rot, unit, fields, footprint, dnp, in_bom, on_board,
                        pin_numbers, prop_positions):
        self.lib_ids.add(lib_id)
        libsym = self.sch.lib.get(lib_id)
        u = uid(self.key, "sym", ref)
        node = [Sym("symbol"), [Sym("lib_id"), lib_id], [Sym("at"), r4(x), r4(y), rot], [Sym("unit"), unit],
                [Sym("body_style"), 1], [Sym("exclude_from_sim"), Sym("no")],
                [Sym("in_bom"), Sym("yes" if in_bom else "no")], [Sym("on_board"), Sym("yes" if on_board else "no")],
                [Sym("in_pos_files"), Sym("yes" if on_board else "no")], [Sym("dnp"), Sym("yes" if dnp else "no")],
                [Sym("uuid"), u]]
        (rx, ry, rj, rhide, ra, reff), (vx, vy, vj, vhide, va, veff) = prop_positions
        node.append(property_("Reference", ref, rx, ry, angle=ra, hide=rhide, justify=rj, eff=reff))
        node.append(property_("Value", value, vx, vy, angle=va, hide=vhide, justify=vj, eff=veff))
        ds = prop(libsym, "Datasheet")
        desc = prop(libsym, "Description")
        node.append(property_("Footprint", footprint, x, y, hide=True))
        node.append(property_("Datasheet", ds[2] if ds else "", x, y, hide=True))
        node.append(property_("Description", desc[2] if desc else "", x, y, hide=True))
        for k, v in fields.items():
            node.append(property_(k, v, x, y, hide=True))
        for n in pin_numbers:
            node.append([Sym("pin"), n, [Sym("uuid"), uid(self.key, "pin", ref, n)]])
        node.append([Sym("instances"), [Sym("project"), self.sch.project,
                                        [Sym("path"), self.path, [Sym("reference"), ref], [Sym("unit"), unit]]]])
        self.items.append(node)

    def power_symbol(self, net, x, y, ox, oy):
        lib_id = self.sch.power[net]
        pin = self.sch.lib.pins(lib_id)[0]
        body = direction(pin.angle)  # library direction from the pin into the symbol body
        rot = next(r for r in (0, 90, 180, 270) if transform(body[0], body[1], r) == (ox, oy))
        self.pwr_count += 1
        ref = f"#PWR{self.sheet.ref_base if self.sheet else 0:03d}{self.pwr_count:02d}"
        libsym = self.sch.lib.get(lib_id)
        veff = find(prop(libsym, "Value"), "effects")
        if oy == 0:
            # sideways symbol: horizontal value text beyond the graphic (stored angle 90 on a 90/270 symbol)
            off = 3.81 + 0.5 * len(net)
            vx, vy, vang = x + ox * off, y, 90
        else:
            vp = find(prop(libsym, "Value"), "at")
            dx, dy = transform(float(vp[1]), float(vp[2]), rot)
            vx, vy, vang = x + dx, y + dy, 0
        self.symbol_instance(lib_id, ref, net, x, y, rot, 1, {}, "", False, False, False, ["1"],
                             ((x, y, None, True, 0, None), (vx, vy, None, False, vang, veff)))

    def place_part(self, p: Part):
        X, Y = p.at
        pins = p.pins()
        npins = len({(q.x, q.y) for q in pins})
        is_power_lib = p.lib_id.startswith("power:")
        # reference/value positions (field angles are stored in the symbol's frame:
        # on a 90°/270° symbol, angle 90 displays horizontally)
        frame = 90 if p.rot in (90, 270) else 0
        if is_power_lib:
            props = ((X, Y + 2.54, None, True, 0, None), (X, Y - 3.81 if p.rot == 0 else Y + 3.81, None, False, 0, None))
        elif npins == 2 and len(pins) == 2:
            vertical_lib = pins[0].x == pins[1].x
            shown_vertical = vertical_lib == (p.rot in (0, 180))
            if shown_vertical:
                j = "right" if p.rot in (180, 90) else "left"  # justification is mirrored by a 180° turn
                props = ((X + 2.54, Y - 1.27, j, False, frame, None), (X + 2.54, Y + 1.27, j, False, frame, None))
            else:
                props = ((X, Y - 3.81, None, False, frame, None), (X, Y + 3.81, None, False, frame, None))
        else:
            libsym = self.sch.lib.get(p.lib_id)
            out = []
            for name in ("Reference", "Value"):
                lp = prop(libsym, name)
                at = find(lp, "at")
                dx, dy = transform(float(at[1]), float(at[2]), p.rot)
                ang = int(float(at[3])) if len(at) > 3 else 0
                out.append((X + dx, Y + dy, None, False, ang, find(lp, "effects")))
            props = tuple(out)
        fields = dict(p.fields)
        self.symbol_instance(p.lib_id, p.ref, p.value, X, Y, p.rot, p.unit, fields, p.footprint, p.dnp,
                             p.in_bom and not is_power_lib, p.on_board and not is_power_lib,
                             [q.number for q in pins], props)
        # connections, one per pin location
        seen = set()
        for q in pins:
            loc = (q.x, q.y)
            if loc in seen:
                continue
            seen.add(loc)
            net = p.nets.get(q.number)
            if net is None:
                continue
            dx, dy = transform(q.x, q.y, p.rot)
            px, py = X + dx, Y + dy
            if net is NC:
                self.no_connect(px, py)
                continue
            if q.number in p.wired:
                continue
            out = direction(q.angle + 180)
            ox, oy = transform(out[0], out[1], p.rot)
            ln = p.stubs.get(q.number, p.stub)
            ex, ey = px + ox * ln, py + oy * ln
            self.wire(px, py, ex, ey)
            if net in self.sch.power:
                self.power_symbol(net, ex, ey, ox, oy)
            else:
                self.label(net, ex, ey, label_angle(ox, oy), net in self.globals)

    # -- file -------------------------------------------------------------------------------------
    def document(self, file_uuid, paper, title, comments=()):
        tb = [Sym("title_block"), [Sym("title"), title], [Sym("date"), self.sch.date], [Sym("rev"), self.sch.rev],
              [Sym("company"), self.sch.company]]
        for i, c in enumerate(comments, 1):
            tb.append([Sym("comment"), i, c])
        libs = [Sym("lib_symbols")] + [self.sch.lib.get(l) for l in sorted(self.lib_ids)]
        doc = [Sym("kicad_sch"), [Sym("version"), VERSION], [Sym("generator"), "tercio-gen"],
               [Sym("generator_version"), "10.0"], [Sym("uuid"), file_uuid], [Sym("paper"), paper], tb, libs]
        doc += self.items
        return doc


def write(sch: Schematic, outdir: pathlib.Path, root_notes_fn=None):
    sch.annotate()
    sch.check()
    outdir.mkdir(parents=True, exist_ok=True)
    root_uuid = uid("root", sch.project)
    used = sch.net_sheets()
    globals_ = {n for n, sheets in used.items() if len(sheets) > 1}

    sheet_uuids = {}
    for sh in sch.sheets:
        su = uid("sheet", sh.file)
        sheet_uuids[sh.file] = su
        w = SheetWriter(sch, sh, root_uuid, su, globals_)
        for b in sh.boxes:
            w.rect(b.x1, b.y1, b.x2, b.y2, b.title)
        for n in sh.notes:
            w.text(n.x, n.y, n.text, n.size, n.bold)
        for p in sh.parts:
            w.place_part(p)
        for pts in sh.wires:
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                w.wire(x1, y1, x2, y2)
        for x, y in sh.junctions:
            w.items.append([Sym("junction"), [Sym("at"), r4(x), r4(y)], [Sym("diameter"), 0], [Sym("color"), 0, 0, 0, 0],
                            [Sym("uuid"), uid(sh.file, "junction", r4(x), r4(y))]])
        for lb in sh.labels:
            w.label(lb.net, lb.x, lb.y, lb.angle, lb.net in globals_)
        for pw in sh.powers:
            ox, oy = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}[pw.angle]
            w.power_symbol(pw.net, pw.x, pw.y, ox, oy)
        doc = w.document(uid("file", sh.file), sh.paper, f"{sch.title} — {sh.title}",
                         comments=(f"Generated by hardware/gen — do not edit by hand", f"Sheet: {sh.file}"))
        doc.append([Sym("embedded_fonts"), Sym("no")])
        (outdir / sh.file).write_text(sexpr.dumps(doc) + "\n")

    # root sheet: one block per sub-sheet plus notes
    w = SheetWriter(sch, None, root_uuid, None, globals_)
    for n in sch.root_notes:
        w.text(n.x, n.y, n.text, n.size, n.bold)
    x0, y0, bw, bh, gap = 30.48, 50.8, 76.2, 25.4, 12.7
    for i, sh in enumerate(sch.sheets):
        col, row = i % 4, i // 4
        x, y = x0 + col * (bw + gap), y0 + row * (bh + gap + 5.08)
        su = sheet_uuids[sh.file]
        w.items.append([Sym("sheet"), [Sym("at"), r4(x), r4(y)], [Sym("size"), bw, bh],
                        [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("yes")], [Sym("on_board"), Sym("yes")],
                        [Sym("dnp"), Sym("no")], [Sym("fields_autoplaced"), Sym("yes")],
                        [Sym("stroke"), [Sym("width"), 0.1524], [Sym("type"), Sym("solid")]],
                        [Sym("fill"), [Sym("color"), 0, 0, 0, 0.0]], [Sym("uuid"), su],
                        [Sym("property"), "Sheetname", sh.title, [Sym("at"), r4(x), r4(y - 0.7116), 0],
                         effects("left bottom")],
                        [Sym("property"), "Sheetfile", sh.file, [Sym("at"), r4(x), r4(y + bh + 0.5884), 0],
                         effects("left top")],
                        [Sym("instances"), [Sym("project"), sch.project,
                                            [Sym("path"), f"/{root_uuid}", [Sym("page"), str(sh.page)]]]]])
    doc = w.document(root_uuid, "A3", sch.title, comments=("Generated by hardware/gen — do not edit by hand",))
    doc.append([Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]])
    doc.append([Sym("embedded_fonts"), Sym("no")])
    (outdir / f"{sch.project}.kicad_sch").write_text(sexpr.dumps(doc) + "\n")

    # project symbol library with the code-defined symbols, so the project is self-contained
    customs = sorted(k for k in sch.lib._custom)
    if customs:
        libname = customs[0].split(":", 1)[0]
        (outdir / "lib").mkdir(exist_ok=True)
        lib = [Sym("kicad_symbol_lib"), [Sym("version"), Sym("20251024")], [Sym("generator"), "tercio-gen"],
               [Sym("generator_version"), "10.0"]]
        for lid in customs:
            sym = sch.lib.get(lid)
            sym[1] = lid.split(":", 1)[1]
            lib.append(sym)
        (outdir / "lib" / f"{libname}.kicad_sym").write_text(sexpr.dumps(lib) + "\n")
        (outdir / "sym-lib-table").write_text(
            "(sym_lib_table\n\t(version 7)\n"
            f'\t(lib (name "{libname}")(type "KiCad")(uri "${{KIPRJMOD}}/lib/{libname}.kicad_sym")(options "")(descr "Tercio B1 symbols, generated"))\n)\n')

    pro = {"meta": {"filename": f"{sch.project}.kicad_pro", "version": 3},
           "sheets": [[root_uuid, "Root"]] + [[sheet_uuids[s.file], s.title] for s in sch.sheets],
           "schematic": {"meta": {"version": 1}}, "boards": [], "text_variables": {}}
    (outdir / f"{sch.project}.kicad_pro").write_text(json.dumps(pro, indent=2) + "\n")
    return root_uuid
