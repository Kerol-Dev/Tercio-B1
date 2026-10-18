"""Symbol library access: KiCad's own libraries plus symbols defined in code.

`Library.get("Device:R")` returns a flattened symbol (derived symbols are
merged with their parent) ready to embed in a schematic's lib_symbols, and
`pins()` lists its pins with connection points and directions.
"""
from __future__ import annotations

import copy
import math
import pathlib
from dataclasses import dataclass

from . import sexpr
from .sexpr import Sym, find, find_all

KICAD_SYMBOLS = pathlib.Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")


@dataclass
class Pin:
    number: str
    name: str
    etype: str  # input, output, bidirectional, tri_state, passive, power_in, power_out, open_collector, no_connect, ...
    x: float  # connection point, library units (mm, y up)
    y: float
    angle: float  # direction from the connection point towards the body
    unit: int
    hidden: bool = False


class Library:
    def __init__(self):
        self._files: dict[str, list] = {}
        self._custom: dict[str, list] = {}

    # -- loading -----------------------------------------------------------------
    def _lib(self, name: str) -> list:
        if name not in self._files:
            path = KICAD_SYMBOLS / f"{name}.kicad_sym"
            self._files[name] = sexpr.loads(path.read_text())
        return self._files[name]

    def _raw(self, lib: str, name: str) -> list:
        for s in find_all(self._lib(lib), "symbol"):
            if s[1] == name:
                return s
        raise KeyError(f"{lib}:{name} not found")

    def add_custom(self, lib_id: str, symbol: list):
        self._custom[lib_id] = symbol

    def get(self, lib_id: str) -> list:
        """Flattened symbol named `lib_id` (e.g. "Device:R"), as embedded in a schematic."""
        if lib_id in self._custom:
            sym = copy.deepcopy(self._custom[lib_id])
            sym[1] = lib_id
            return sym
        lib, name = lib_id.split(":", 1)
        raw = copy.deepcopy(self._raw(lib, name))
        ext = find(raw, "extends")
        if ext is not None:
            parent = self.get(f"{lib}:{ext[1]}")
            pname = parent[1].split(":", 1)[1]
            # Child properties override the parent's; units and graphics come from the parent.
            merged = [Sym("symbol"), lib_id]
            child_props = {p[1]: p for p in find_all(raw, "property")}
            for item in parent[2:]:
                if isinstance(item, list) and item and item[0] == "property" and item[1] in child_props:
                    merged.append(child_props.pop(item[1]))
                elif isinstance(item, list) and item and item[0] == "symbol":
                    unit = copy.deepcopy(item)
                    unit[1] = unit[1].replace(pname, name, 1)
                    merged.append(unit)
                else:
                    merged.append(item)
            # child-only properties go before the unit symbols
            insert_at = next(i for i, it in enumerate(merged) if isinstance(it, list) and it and it[0] == "symbol")
            for p in child_props.values():
                merged.insert(insert_at, p)
                insert_at += 1
            return merged
        raw[1] = lib_id
        return raw

    def pins(self, lib_id: str) -> list[Pin]:
        sym = self.get(lib_id)
        out = []
        for unit in find_all(sym, "symbol"):
            # unit names end in _<unit>_<style>
            parts = unit[1].rsplit("_", 2)
            unit_no = int(parts[-2]) if len(parts) >= 3 and parts[-2].isdigit() else 1
            style = int(parts[-1]) if parts[-1].isdigit() else 1
            if style not in (0, 1):
                continue
            for p in find_all(unit, "pin"):
                at = find(p, "at")
                hidden = any(isinstance(k, Sym) and k == "hide" for k in p) or (find(p, "hide") is not None and find(p, "hide")[1] == "yes")
                out.append(Pin(number=find(p, "number")[1], name=find(p, "name")[1], etype=str(p[1]),
                               x=float(at[1]), y=float(at[2]), angle=float(at[3]) if len(at) > 3 else 0.0,
                               unit=unit_no, hidden=hidden))
        return out


# ---- placement transform -------------------------------------------------------------
def transform(dx: float, dy: float, rot: int, mirror_x: bool = False) -> tuple[float, float]:
    """Library offset (y up) -> schematic offset (y down) for a symbol rotation in degrees."""
    x, y = dx, -dy
    if mirror_x:
        x = -x
    rot %= 360
    if rot == 0:
        return x, y
    if rot == 90:
        return y, -x
    if rot == 180:
        return -x, -y
    if rot == 270:
        return -y, x
    raise ValueError(rot)


def direction(angle: float) -> tuple[float, float]:
    a = math.radians(angle)
    return round(math.cos(a)), round(math.sin(a))


# ---- building custom symbols in code ------------------------------------------------------
def _font():
    return [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]


def _prop(name, value, x, y, hide=False, justify=None):
    eff = _font()
    if justify:
        eff.append([Sym("justify")] + [Sym(j) for j in justify.split()])
    p = [Sym("property"), name, value, [Sym("at"), x, y, 0]]
    if hide:
        p.append([Sym("hide"), Sym("yes")])
    p.append(eff)
    return p


def make_ic(name: str, ref: str, footprint: str, datasheet: str, description: str,
            left: list, right: list, top: list = (), bottom: list = (), width: float = 20.32,
            pin_len: float = 2.54) -> list:
    """A rectangular IC symbol. Each side is a list of (number, name, etype) or None for a gap.

    Pins run top-to-bottom on the left/right sides and left-to-right on top/bottom,
    on a 2.54 mm pitch. Returns the S-expression (name without library prefix).
    """
    rows = max(len(left), len(right))
    height = (rows + 1) * 2.54
    h2 = round(height / 2 / 1.27) * 1.27
    w2 = width / 2
    body = [Sym("symbol"), f"{name}_0_1",
            [Sym("rectangle"), [Sym("start"), -w2, h2], [Sym("end"), w2, -h2],
             [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]],
             [Sym("fill"), [Sym("type"), Sym("background")]]]]
    pins_unit = [Sym("symbol"), f"{name}_1_1"]

    def pin(num, pname, etype, x, y, ang):
        hidden = etype == "no_connect"
        p = [Sym("pin"), Sym(etype), Sym("line"), [Sym("at"), x, y, ang], [Sym("length"), pin_len]]
        if hidden:
            p.append([Sym("hide"), Sym("yes")])
        p += [[Sym("name"), pname, _font()], [Sym("number"), str(num), _font()]]
        pins_unit.append(p)

    y0 = h2 - 2.54
    for i, item in enumerate(left):
        if item:
            pin(item[0], item[1], item[2], -w2 - pin_len, round(y0 - i * 2.54, 4), 0)
    for i, item in enumerate(right):
        if item:
            pin(item[0], item[1], item[2], w2 + pin_len, round(y0 - i * 2.54, 4), 180)
    x0 = -((len(top) - 1) * 2.54) / 2
    for i, item in enumerate(top):
        if item:
            pin(item[0], item[1], item[2], round(x0 + i * 2.54, 4), h2 + pin_len, 270)
    x0 = -((len(bottom) - 1) * 2.54) / 2
    for i, item in enumerate(bottom):
        if item:
            pin(item[0], item[1], item[2], round(x0 + i * 2.54, 4), -h2 - pin_len, 90)

    return [Sym("symbol"), name,
            [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("yes")], [Sym("on_board"), Sym("yes")],
            _prop("Reference", ref, -w2, h2 + 1.27, justify="right bottom"),
            _prop("Value", name, w2, h2 + 1.27, justify="left bottom"),
            _prop("Footprint", footprint, 0, 0, hide=True),
            _prop("Datasheet", datasheet, 0, 0, hide=True),
            _prop("Description", description, 0, 0, hide=True),
            body, pins_unit,
            [Sym("embedded_fonts"), Sym("no")]]
