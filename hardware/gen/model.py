"""The circuit model: sheets, placed parts and net assignments.

Circuit code places parts and connects pins to named nets:

    r = sh.part("Device:R", "100k", (120, 60), fp=R0603, lcsc="C25803")
    r[1] = "VBUS"
    r[2] = "VBUS_SENSE"
    u["PA0"] = "CSA_A"      # by pin name (unique names only)
    u["PB8"] = NC           # explicit no-connect

Every visible pin must be assigned (a net or NC), so forgotten pins are an
error rather than a silent dangling input.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .symbols import Library, Pin, transform

NC = object()  # marker for an intentional no-connect
GRID = 1.27


def snap(v: float) -> float:
    """Round to KiCad's 1.27 mm connection grid."""
    return round(round(v / GRID) * GRID, 4)


@dataclass
class Part:
    sheet: "Sheet"
    lib_id: str
    value: str
    at: tuple[float, float]
    rot: int
    ref_prefix: str
    footprint: str
    fields: dict[str, str]
    dnp: bool
    unit: int
    stub: float
    ref: str = ""
    nets: dict[str, object] = field(default_factory=dict)  # pin number -> net name | NC
    stubs: dict[str, float] = field(default_factory=dict)  # pin number -> custom stub length
    wired: set = field(default_factory=set)  # pin numbers the circuit code wires explicitly (no stub)
    in_bom: bool = True
    on_board: bool = True

    def pins(self) -> list[Pin]:
        return [p for p in self.sheet.schematic.lib.pins(self.lib_id) if p.unit in (0, self.unit)]

    def _pin_number(self, key) -> str:
        key = str(key)
        pins = self.pins()
        numbers = {p.number for p in pins}
        if key in numbers:
            return key
        named = [p for p in pins if p.name == key and not p.hidden]
        if len(named) == 1:
            return named[0].number
        if not named:
            raise KeyError(f"{self.lib_id}: no pin {key!r}")
        raise KeyError(f"{self.lib_id}: pin name {key!r} is ambiguous; use the number")

    def __setitem__(self, key, net):
        num = self._pin_number(key)
        if num in self.nets and self.nets[num] is not net and self.nets[num] != net:
            raise ValueError(f"{self.ref or self.lib_id} pin {num} already on {self.nets[num]}")
        self.nets[num] = net

    def connect(self, **kw):
        for k, v in kw.items():
            self[k] = v
        return self

    def xy(self, key) -> tuple[float, float]:
        """Schematic coordinates of a pin's connection point."""
        num = self._pin_number(key)
        q = next(p for p in self.pins() if p.number == num)
        dx, dy = transform(q.x, q.y, self.rot)
        return round(self.at[0] + dx, 4), round(self.at[1] + dy, 4)

    def wire_to(self, key, net):
        """Assign `net` and leave the drawing to explicit Sheet.wire() calls; returns the pin point."""
        self[key] = net
        self.wired.add(self._pin_number(key))
        return self.xy(key)

    def stub_len(self, key, length: float):
        self.stubs[self._pin_number(key)] = length
        return self


@dataclass
class Note:
    x: float
    y: float
    text: str
    size: float = 1.27
    bold: bool = False


@dataclass
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    title: str


@dataclass
class Label:
    net: str
    x: float
    y: float
    angle: int  # 0 right, 90 up, 180 left, 270 down


class Sheet:
    def __init__(self, schematic: "Schematic", file: str, title: str, page: int, ref_base: int, paper: str = "A3"):
        self.schematic = schematic
        self.file = file
        self.title = title
        self.page = page
        self.ref_base = ref_base
        self.paper = paper
        self.parts: list[Part] = []
        self.notes: list[Note] = []
        self.boxes: list[Box] = []
        self.wires: list[list[tuple[float, float]]] = []
        self.junctions: list[tuple[float, float]] = []
        self.labels: list[Label] = []
        self.powers: list[Label] = []

    def wire(self, *pts):
        """Polyline through `pts` (each segment horizontal or vertical)."""
        self.wires.append([(snap(x), snap(y)) for x, y in pts])

    def junction(self, x, y):
        self.junctions.append((snap(x), snap(y)))

    def label(self, net, x, y, angle=0):
        self.labels.append(Label(net, snap(x), snap(y), angle))

    def power(self, net, x, y, angle=90):
        """Power symbol at (x, y) pointing in `angle` (90 = up, 270 = down)."""
        self.powers.append(Label(net, snap(x), snap(y), angle))

    def part(self, lib_id: str, value: str, at, rot: int = 0, fp: str = "", ref: str = "", lcsc: str = "",
             mpn: str = "", dnp: bool = False, unit: int = 1, stub: float = 2.54, **fields) -> Part:
        prefix = ref or self.schematic.default_prefix(lib_id)
        f = {}
        if lcsc:
            f["LCSC"] = lcsc
        if mpn:
            f["MPN"] = mpn
        f.update(fields)
        p = Part(self, lib_id, value, (snap(at[0]), snap(at[1])), rot, prefix, fp, f, dnp, unit, stub)
        self.parts.append(p)
        return p

    def note(self, x, y, text, size=1.27, bold=False):
        self.notes.append(Note(x, y, text, size, bold))

    def box(self, x1, y1, x2, y2, title=""):
        self.boxes.append(Box(x1, y1, x2, y2, title))


class Schematic:
    def __init__(self, project: str, title: str, rev: str, company: str, date: str):
        self.project = project
        self.title = title
        self.rev = rev
        self.company = company
        self.date = date
        self.lib = Library()
        self.sheets: list[Sheet] = []
        self.root_notes: list[Note] = []
        # power nets drawn with power symbols instead of labels
        self.power = {"GND": "power:GND", "+3V3": "power:+3V3", "+5V": "power:+5V",
                      "VBUS": "power:VBUS", "+3.3VA": "power:+3.3VA"}

    def sheet(self, file, title, page, ref_base, paper="A3") -> Sheet:
        s = Sheet(self, file, title, page, ref_base, paper)
        self.sheets.append(s)
        return s

    @staticmethod
    def default_prefix(lib_id: str) -> str:
        name = lib_id.split(":", 1)[1]
        table = [("R_Shunt", "R"), ("Thermistor", "TH"), ("Polyfuse", "F"), ("FerriteBead", "FB"),
                 ("SolderJumper", "JP"), ("MountingHole", "H"), ("TestPoint", "TP"), ("Crystal", "Y"),
                 ("LED", "D"), ("D_", "D"), ("Conn_", "J"), ("TagConnect", "J"), ("C_", "C"), ("L", "L"),
                 ("R", "R"), ("C", "C")]
        if lib_id.startswith("Device:"):
            for k, v in table:
                if name.startswith(k) or name == k:
                    return v
        if lib_id.startswith("Transistor_FET:"):
            return "Q"
        if lib_id.startswith(("Connector", "Connector_Generic")):
            return "J"
        if lib_id.startswith("Jumper:"):
            return "JP"
        if lib_id.startswith("Mechanical:"):
            return "H"
        if lib_id.startswith("Power_Protection:"):
            return "D"
        return "U"

    # -- annotation & checks ---------------------------------------------------------------
    def annotate(self):
        for sh in self.sheets:
            counters: dict[str, int] = {}
            for p in sh.parts:
                n = counters.get(p.ref_prefix, 0) + 1
                counters[p.ref_prefix] = n
                p.ref = f"{p.ref_prefix}{sh.ref_base + n}"

    def check(self):
        errors = []
        for sh in self.sheets:
            for p in sh.parts:
                groups: dict[tuple, list[Pin]] = {}
                for pin in p.pins():
                    groups.setdefault((pin.x, pin.y), []).append(pin)
                for pins in groups.values():
                    nets = {"<NC>" if p.nets[x.number] is NC else p.nets[x.number] for x in pins if x.number in p.nets}
                    if len(nets) > 1:
                        errors.append(f"{p.ref}: stacked pins {[x.number for x in pins]} on different nets")
                    visible = [x for x in pins if not x.hidden and x.etype != "no_connect"]
                    if visible and not any(x.number in p.nets for x in pins):
                        errors.append(f"{sh.file} {p.ref} ({p.value}): pin {visible[0].number} {visible[0].name} unassigned")
                    # propagate the net to hidden stacked pins
                    assigned = [p.nets[x.number] for x in pins if x.number in p.nets]
                    if assigned:
                        for x in pins:
                            p.nets.setdefault(x.number, assigned[0])
        if errors:
            raise SystemExit("schematic check failed:\n  " + "\n  ".join(errors))

    def net_sheets(self) -> dict[str, set[str]]:
        used: dict[str, set[str]] = {}
        for sh in self.sheets:
            for p in sh.parts:
                for n in p.nets.values():
                    if n is not NC:
                        used.setdefault(n, set()).add(sh.file)
        return used

    def intended_netlist(self) -> dict[str, set[tuple[str, str]]]:
        """Net name -> {(ref, pin)} for real parts (power flags are not netlist members)."""
        nets: dict[str, set[tuple[str, str]]] = {}
        for sh in self.sheets:
            for p in sh.parts:
                if p.lib_id.startswith("power:"):
                    continue
                for num, n in p.nets.items():
                    if n is not NC:
                        nets.setdefault(n, set()).add((p.ref, num))
        return nets

    def no_connects(self) -> set[tuple[str, str]]:
        """Explicit NC pins plus pins the symbol itself types as no_connect."""
        out = set()
        for sh in self.sheets:
            for p in sh.parts:
                out |= {(p.ref, num) for num, n in p.nets.items() if n is NC}
                out |= {(p.ref, q.number) for q in p.pins() if q.etype == "no_connect" and q.number not in p.nets}
        return out
