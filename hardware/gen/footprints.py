"""Project footprints defined in code (written to <kicad>/lib/Tercio_B1.pretty).

R_2512_Kelvin   KiCad's R_2512_6332Metric plus two sense pads at the inner edges of the
                terminals (overlapping them by 0.05 mm), tied with net_tie_pad_groups. Pads 1/4 carry
                current; 2/3 are the Kelvin taps (pin numbers match Device:R_Shunt).
MotorPad_3.6x6mm  Plated 3.6 × 6 mm pad with a 1.8 mm hole for a 16–18 AWG motor lead.
TestPad_D0.9mm  Compact SMD test pad: 0.9 mm round, 1.2 mm courtyard (KiCad's D1.0 needs 2.1 mm), so a
                test point fits beside the part it probes instead of at the end of a long stub.
"""
from __future__ import annotations

import copy
import pathlib

from . import sexpr
from .sexpr import Sym, find, find_all

KICAD_FP = pathlib.Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")
LIB = "Tercio_B1"


def _font(size=1.0, thick=0.15):
    return [Sym("effects"), [Sym("font"), [Sym("size"), size, size], [Sym("thickness"), thick]]]


def _prop(name, value, x, y, layer, hide=False):
    p = [Sym("property"), name, value, [Sym("at"), x, y, 0], [Sym("layer"), layer]]
    if hide:
        p.append([Sym("hide"), Sym("yes")])
    p.append(_font())
    return p


def r2512_kelvin():
    base = sexpr.loads((KICAD_FP / "Resistor_SMD.pretty" / "R_2512_6332Metric.kicad_mod").read_text())
    fp = [Sym("footprint"), "R_2512_Kelvin"]
    for item in base[2:]:
        if not isinstance(item, list):
            continue
        head = item[0]
        if head == "pad":
            continue
        if head == "descr":
            item = [Sym("descr"), "2512 current-sense resistor with Kelvin sense pads (net tie): pads 1/4 current, 2/3 sense. "
                                  "Based on KiCad R_2512_6332Metric."]
        if head == "tags":
            item = [Sym("tags"), "resistor shunt kelvin 2512"]
        if head == "generator":
            item = [Sym("generator"), "tercio-gen"]
        if head == "property" and item[1] == "Value":
            item = copy.deepcopy(item)
            item[2] = "R_2512_Kelvin"
        fp.append(item)
    pads = find_all(base, "pad")
    # power pads keep KiCad's geometry; renumber the second one to 4
    p1, p4 = copy.deepcopy(pads[0]), copy.deepcopy(pads[1])
    p4[1] = "4"
    fp += [p1, p4]
    # sense taps at the inner edges of the terminals (the Kelvin point of a 2-terminal shunt): each overlaps
    # its power pad by 0.05 mm (the tie) and reaches 0.45 mm inward, so a sense trace can leave toward the
    # middle of the resistor with full clearance from the power pads
    inner = 2.9625 - 1.225 / 2
    for num, sgn in (("2", -1), ("3", 1)):
        fp.append([Sym("pad"), num, Sym("smd"), Sym("roundrect"), [Sym("at"), sgn * (inner - 0.2), 0],
                   [Sym("size"), 0.5, 0.6], [Sym("layers"), "F.Cu", "F.Mask"], [Sym("roundrect_rratio"), 0.25]])
    fp.insert(fp.index(next(i for i in fp if isinstance(i, list) and i[0] == "fp_line")),
              [Sym("net_tie_pad_groups"), "1, 2", "3, 4"])
    return fp


def motor_pad():
    return [Sym("footprint"), "MotorPad_3.6x6mm",
            [Sym("version"), Sym("20260206")], [Sym("generator"), "tercio-gen"], [Sym("layer"), "F.Cu"],
            [Sym("descr"), "Motor phase pad, 3.6 x 6 mm plated, 1.8 mm hole, for a 16-18 AWG lead"],
            [Sym("tags"), "pad motor wire"],
            _prop("Reference", "REF**", 0, -4.2, "F.SilkS"),
            _prop("Value", "MotorPad_3.6x6mm", 0, 4.2, "F.Fab"),
            _prop("Datasheet", "", 0, 0, "F.Fab", hide=True),
            _prop("Description", "", 0, 0, "F.Fab", hide=True),
            [Sym("attr"), Sym("through_hole"), Sym("exclude_from_pos_files"), Sym("exclude_from_bom")],
            [Sym("fp_rect"), [Sym("start"), -2.1, -3.3], [Sym("end"), 2.1, 3.3],
             [Sym("stroke"), [Sym("width"), 0.05], [Sym("type"), Sym("default")]], [Sym("fill"), Sym("no")],
             [Sym("layer"), "F.CrtYd"]],
            [Sym("pad"), "1", Sym("thru_hole"), Sym("roundrect"), [Sym("at"), 0, 0], [Sym("size"), 3.6, 6],
             [Sym("drill"), 1.8], [Sym("layers"), "*.Cu", "*.Mask"], [Sym("roundrect_rratio"), 0.15]],
            [Sym("embedded_fonts"), Sym("no")]]


def swd_pads():
    """1 × 5 SMD pads on a 2.54 mm pitch: 3V3, SWDIO, SWCLK, NRST, GND (the S1/FD SWD order)."""
    fp = [Sym("footprint"), "SWD_Pads_1x05_P2.54mm",
          [Sym("version"), Sym("20260206")], [Sym("generator"), "tercio-gen"], [Sym("layer"), "F.Cu"],
          [Sym("descr"), "SWD pogo/solder pads, 1x05, 2.54 mm pitch: 3V3, SWDIO, SWCLK, NRST, GND"],
          [Sym("tags"), "swd debug pads"],
          _prop("Reference", "REF**", 0, -2.0, "F.SilkS"),
          _prop("Value", "SWD", 0, 2.0, "F.Fab"),
          _prop("Datasheet", "", 0, 0, "F.Fab", hide=True),
          _prop("Description", "", 0, 0, "F.Fab", hide=True),
          [Sym("attr"), Sym("smd"), Sym("exclude_from_pos_files"), Sym("exclude_from_bom")],
          [Sym("fp_rect"), [Sym("start"), -6.0, -1.15], [Sym("end"), 6.0, 1.15],
           [Sym("stroke"), [Sym("width"), 0.05], [Sym("type"), Sym("default")]], [Sym("fill"), Sym("no")],
           [Sym("layer"), "F.CrtYd"]],
          [Sym("fp_circle"), [Sym("center"), -5.08, -1.5], [Sym("end"), -4.98, -1.5],
           [Sym("stroke"), [Sym("width"), 0.2], [Sym("type"), Sym("solid")]], [Sym("fill"), Sym("yes")],
           [Sym("layer"), "F.SilkS"]]]
    for i in range(5):
        fp.append([Sym("pad"), str(i + 1), Sym("smd"), Sym("circle"), [Sym("at"), round(-5.08 + i * 2.54, 3), 0],
                   [Sym("size"), 1.5, 1.5], [Sym("layers"), "F.Cu", "F.Mask"]])
    fp.append([Sym("embedded_fonts"), Sym("no")])
    return fp


def test_pad():
    return [Sym("footprint"), "TestPad_D0.9mm",
            [Sym("version"), Sym("20260206")], [Sym("generator"), "tercio-gen"], [Sym("layer"), "F.Cu"],
            [Sym("descr"), "Compact SMD test pad, 0.9 mm round, for scope probe tips and pogo pins"],
            [Sym("tags"), "test point pad"],
            _prop("Reference", "REF**", 0, -1.2, "F.SilkS"),
            _prop("Value", "TestPad_D0.9mm", 0, 1.2, "F.Fab"),
            _prop("Datasheet", "", 0, 0, "F.Fab", hide=True),
            _prop("Description", "", 0, 0, "F.Fab", hide=True),
            [Sym("attr"), Sym("smd"), Sym("exclude_from_pos_files"), Sym("exclude_from_bom")],
            [Sym("fp_rect"), [Sym("start"), -0.6, -0.6], [Sym("end"), 0.6, 0.6],
             [Sym("stroke"), [Sym("width"), 0.05], [Sym("type"), Sym("default")]], [Sym("fill"), Sym("no")],
             [Sym("layer"), "F.CrtYd"]],
            [Sym("pad"), "1", Sym("smd"), Sym("circle"), [Sym("at"), 0, 0], [Sym("size"), 0.9, 0.9],
             [Sym("layers"), "F.Cu", "F.Mask"]],
            [Sym("embedded_fonts"), Sym("no")]]


def write(outdir: pathlib.Path):
    lib = outdir / "lib" / f"{LIB}.pretty"
    lib.mkdir(parents=True, exist_ok=True)
    for fp in (r2512_kelvin(), motor_pad(), swd_pads(), test_pad()):
        (lib / f"{fp[1]}.kicad_mod").write_text(sexpr.dumps(fp) + "\n")
    (outdir / "fp-lib-table").write_text(
        "(fp_lib_table\n\t(version 7)\n"
        f'\t(lib (name "{LIB}")(type "KiCad")(uri "${{KIPRJMOD}}/lib/{LIB}.pretty")(options "")(descr "Tercio B1 footprints, generated"))\n)\n')
