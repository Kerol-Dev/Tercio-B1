"""Approximate 3D model of the AMASS XT30PW-M (KiCad 10 ships none).

Built from the KiCad footprint geometry: pins at (0, 0) and (-5, 0), mounting
pegs at (-8, -10) and (3, -10), courtyard x -9.7..4.7, y -13.6..2.3.
Body is XT30 yellow, 10.2 mm wide, 5.2 mm tall, mating face at footprint y = -13.4.
Run with a Python that has CadQuery:

    ~/Documents/Projects/Tercio-s1/Hardware/CAD/NEMA23-Adapter/.venv/bin/python hardware/tools/xt30pw_model.py
"""
import pathlib

import cadquery as cq

OUT = pathlib.Path(__file__).resolve().parent.parent / "kicad" / "lib" / "3d" / "AMASS_XT30PW-M.step"
YELLOW = cq.Color(0.93, 0.74, 0.10)
GOLD = cq.Color(0.85, 0.68, 0.30)

# KiCad model space: x right, y = -footprint y, z up from the board surface
cx = -2.5            # body centre between the pins
front, back = 13.4, -1.6   # model y of the mating face and the rear
w, h = 10.2, 5.2

body = (cq.Workplane("XY").box(w, front - back, h, centered=(True, False, False))
        .translate((cx, back, 0))
        .edges("|Y and >Z and <X").chamfer(1.6)     # the XT30 "D" profile: two chamfered top corners on one side
        .edges("|Y and >Z and >X").fillet(0.6))
# side flanges with the PCB locating pegs
flange = (cq.Workplane("XY").box(13.6, 3.4, 1.3, centered=(True, True, False)).translate((cx, 10.0, 0)))
body = body.union(flange)
# two contact openings in the mating face (cut inward, toward -y)
V = cq.Vector
for x in (0.0, -5.0):
    body = body.cut(cq.Workplane().add(cq.Solid.makeCylinder(1.45, 9.0, V(x, front + 0.01, 2.6), V(0, -1, 0))))

parts = cq.Assembly()
parts.add(body, name="housing", color=YELLOW)
for x in (0.0, -5.0):
    pin = cq.Solid.makeCylinder(0.55, 8.4, V(x, front - 0.8, 2.6), V(0, -1, 0))          # contact inside the opening
    tail = cq.Solid.makeBox(1.4, 2.4, 1.0, V(x - 0.7, -1.6, 2.1))                        # exits the rear of the body
    leg = cq.Solid.makeCylinder(0.7, 6.6, V(x, -0.0, 3.0), V(0, 0, -1))                  # down through the PCB
    parts.add(cq.Workplane().add(pin).union(cq.Workplane().add(tail)).union(cq.Workplane().add(leg)),
              name=f"contact_{int(-x)}", color=GOLD)
for x in (-8.0, 3.0):
    parts.add(cq.Workplane().add(cq.Solid.makeCylinder(0.65, 2.9, V(x, 10.0, 1.3), V(0, 0, -1))), name=f"peg_{int(-x)}",
              color=YELLOW)

OUT.parent.mkdir(parents=True, exist_ok=True)
parts.save(str(OUT), exportType="STEP")
print("wrote", OUT)
