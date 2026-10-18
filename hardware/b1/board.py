"""Tercio B1 rev A — placement plan (46 × 46 mm, centre = motor shaft axis).

Top side: power input, power stage, gate driver + buck, connectors, LEDs.
Bottom side: MT6835 on the shaft axis, MCU, CAN transceiver, LDO, logic passives,
test points. The bottom under the power stage is kept for a heat-spreader pad
except for a few 0402/0603 parts (gate resistors, snubbers, NTC, phase taps).

Edges: power in on the left (XT30), phases on the bottom, CAN + aux on top.
"""
from gen.pcb import Rect

# leg columns: FET column centre x, shunt column x (shunts sit left of their low-side FET)
LEGS = {"A": -9.2, "B": 1.8, "C": 12.8}
Y_HS, Y_LS = 7.4, 14.9
SHUNT_DX = -5.25
FETS = {"A": ("Q301", "Q302"), "B": ("Q303", "Q304"), "C": ("Q305", "Q306")}
SHUNTS = {"A": "R303", "B": "R307", "C": "R311"}
PADS = {"A": "J301", "B": "J302", "C": "J303"}

LABEL = (0.0, 0.0, 2.9, 0.0)   # room a test point keeps beside it for its silkscreen name (b1/art.py)
CSA_TP = Rect(-23, -23, 23, 4.9)   # the CSA test points may use the strip just under the logic half
MCU = (13.0, -10.0)   # U401 centre (bottom, rotated 180°): see place()
HOLES = ((-19.5, -19.5), (19.5, -19.5), (-19.5, 19.5), (19.5, 19.5))
TOP_LOGIC = Rect(-23, -23, 23, 3.3)
BOT_LOGIC = Rect(-23, -23, 23, 3.3)
BOT_POWER = Rect(-23, 3.3, 23, 23)


def place(p):
    # a wider keep-clear ring around the MCU: its 48 pins at 0.5 mm need room to fan out before the
    # resistors and caps around it (the fast router showed the outer layers jammed there)
    p.fan_rings = {"U401": 0.8}
    # ---- mechanics ------------------------------------------------------------------------
    for ref, (x, y) in zip(("H101", "H102", "H103", "H104"), HOLES):
        p.place(ref, x, y)
        p.keepout_circle(x, y, 3.0)  # M2.5 head + washer

    # ---- top: power input -------------------------------------------------------------------
    p.place("J101", -9.4, -7.0, rot=90)           # XT30PW-M, body to the left edge; pad 2 (+) below pad 1 (−)
    p.place("C101", 12.6, -0.7)                   # 22 µF 100 V can, right of the driver

    # ---- top: power stage ----------------------------------------------------------------------
    for ph, xf in LEGS.items():
        hs, ls = FETS[ph]
        p.place(hs, xf, Y_HS, rot=90)              # drain up (V_BUS), source down (phase)
        p.place(ls, xf, Y_LS, rot=90)              # drain up (phase), source down (shunt), gate bottom-right
        p.place(SHUNTS[ph], xf + SHUNT_DX, Y_LS, rot=90)   # pad 1 (LSRC) bottom, pad 4 (GND) top
        p.place(PADS[ph], xf, 20.6, rot=90)        # phase pad on the bottom edge
    # bulk MLCC slots: above each shunt (10 µF + 100 nF), plus two each at the left and right edges
    # rot 270: pad 1 (V_BUS) up toward the high-side drains, pad 2 (GND) down toward the shunt return;
    # the second edge caps (rot 90) are flipped so their GND pads share the edge GND pour
    slots = [("C102", -18.9, 6.2, 270), ("C304", -18.9, 11.0, 90), ("C305", -14.45, 6.2, 270), ("C306", -3.45, 6.2, 270),
             ("C307", 7.55, 6.2, 270), ("C308", 17.9, 6.2, 270), ("C309", 17.9, 11.0, 90)]
    for ref, x, y, r in slots:
        p.place(ref, x, y, rot=r)
    for ref, x in (("C310", -14.45), ("C311", -3.45), ("C312", 7.55)):
        p.place(ref, x, 9.8)

    # ---- top: driver ------------------------------------------------------------------------------
    p.place("U201", 1.0, -6.0)                    # thermal vias end 1.2 mm from the encoder (bottom, centre);
    #                                               x leaves a 3.7 mm band between the XT30 and the left pins
    # buck, above the DRV's top pins (48 FB … 43 VIN, 42 SW, 41 GND, 40 DVDD, 39–37 INx at 0.5 mm):
    # the catch diode lies across the top with its cathode straight above SW (pin 42), its anode
    # clear of the INx/DVDD fan; the VIN cap sits up-left where VIN turns after the left fan
    p.place("D201", 2.65, -14.2)                  # SOD-123FL, K over pin 42, A over pins 37–38
    p.place("C203", -1.3, -14.0, rot=180)         # V_BUS pad on the right, toward pin 43
    p.place("L201", 11.3, -8.3)
    # escape fans for the gate-drive and current-sense pins (gen/router.py needs room to leave the QFN):
    # pins 8–12 (phase A) to the left and down, pins 13–24 (phases B, C, SOx) straight down
    p.keepout_rect(-7.2, -5.55, -3.35, 3.3, sides=("T",), name="gate fan A")
    p.keepout_rect(-2.3, -2.15, 4.4, 3.3, sides=("T",), name="gate fan BC")
    p.keepout_rect(-2.4, -12.9, 5.4, -10.1, sides=("T",), name="buck fan")      # top pins' escapes
    p.keepout_rect(4.4, -12.6, 7.6, -3.0, sides=("T",), name="right fan")       # pins 25–39 → vias to the MCU
    p.keepout_rect(-7.2, -9.3, -3.35, -5.55, sides=("T",), name="supply fan")   # pins 2–7, to C207/C202 and vias
    # DRV supply caps, by hand: the 3.2 mm band between the XT30 courtyard and the left pins, above the fan
    # the charge-pump caps (tens of mA) go under the band on the bottom, through vias, so pins 2–7
    # can fan out on top to the VGLS and VM caps; the VCP and flying caps sit right below their pins
    p.place("C206", -4.6, -6.9, rot=90, side="B")   # VCP (high-side gate supply), pins 6–7
    p.place("C205", -6.2, -7.6, rot=90, side="B")   # charge-pump flying cap, pins 3–4
    p.place("C207", -4.65, -10.4, rot=90)         # VGLS (low-side gate supply), pin 2
    p.place("C202", -6.3, -10.4, rot=90)          # VM 100 nF (0603), pin 5

    # ---- top: connectors -------------------------------------------------------------------------------
    # right-angle GH: cable entry is on the mounting-tab side (+y in the footprint) → face it off the board.
    # The aux connector sits top right, straight above the MCU's aux pins (PA15, PB3–PB7 face up);
    # CAN in takes the top left, CAN out the right edge, the transceiver between them
    p.place("J701", 8.5, -19.4, rot=180)          # aux GH-8, entry at the top edge
    p.place("J601", -6.5, -19.4, rot=180)         # CAN GH-4 (in), entry at the top edge
    p.place("J602", 19.4, -10.5, rot=90)          # CAN GH-4 (out), entry at the right edge
    # status (green) and fault (red) LEDs side by side at the right edge, under CAN out, labels beside them
    p.place("D401", 18.5, -3.6, rot=90)
    p.place("D402", 18.5, 0.2, rot=90)

    # ---- bottom: sensor, MCU, CAN ----------------------------------------------------------------------
    # The MCU sits beside the driver, under its right-hand pins: rotated 180° its PB11–PA10 side (DRV_nCS,
    # the six PWM inputs, CAN) faces the DRV's pins 32–39 across a 3 mm via lane, the aux pins face the
    # aux connector, PB0–PB2 (currents) and SPI face the encoder and the DRV's SO / SPI corner, the
    # crystal and the slow analog inputs face the free right edge. The encoder is turned 180° so its
    # SPI pins face the MCU too (its angle offset is calibrated anyway).
    p.place("U501", 0.0, 0.0, rot=180, side="B")  # MT6835 exactly on the shaft axis
    p.place("U401", *MCU, rot=180, side="B")
    p.place("U601", -2.5, -15.5, rot=180, side="B")  # TXD/RXD face the MCU's PA11/PA12, CANH/L face J601
    p.keepout_rect(4.2, -13.4, 7.9, -1.6, sides=("B",), name="drv link vias")   # DRV pins 23–39 → MCU
    # phase A's gate loop leaves the DRV's left pins and drops through here to the bottom / In3
    p.keepout_rect(-7.2, -5.55, -5.1, 3.3, sides=("B",), name="gate A vias")

    # keep the bottom under the power stage clear except for the small parts placed there below;
    # reserve the phase via rows and the GND/V_BUS via spots of b1/copper.py
    for xf in LEGS.values():
        p.keepout_rect(xf - 2.7, Y_HS + 3.1, xf + 2.7, Y_HS + 4.45, sides=("B",), name="phase vias")
        xs = xf + SHUNT_DX
        p.keepout_rect(xs - 1.6, Y_HS + 1.6, xs + 1.6, Y_HS + 2.8, sides=("B",), name="gnd vias")
        p.keepout_rect(xs - 1.6, Y_LS - 3.8, xs + 1.6, Y_LS - 2.6, sides=("B",), name="gnd vias")
        p.keepout_rect(xf - 1.4, 3.5, xf + 1.4, 4.4, sides=("B",), name="vbus vias")
    gate = lambda q: (q, "4")
    T, B = "T", "B"
    # the identity art (b1/art.py: mark + name, 13 × 2.9 mm) owns this spot on the bottom, and the phase
    # letters theirs beside each motor pad
    p.keepout_rect(-5.6, 5.0, 7.6, 8.0, sides=("B",), name="art")
    for xf in LEGS.values():
        p.keepout_rect(xf - 5.2, 19.2, xf - 2.8, 22.0, sides=("B",), name="art")
    # bottom, under the power stage, but outside the phase pours (b1/copper.py: x_f ± 2.6 from the
    # high-side sources down to the pad) so nothing is boxed in by phase copper:
    # gate resistors at the gates, snubbers, NTC, phase taps
    for xf in LEGS.values():
        p.keepout_rect(xf - 2.75, Y_HS + 2.1, xf + 2.75, 23.0, sides=("B",), name="phase pour")
    for ph in "ABC":
        hs, ls = FETS[ph]
        for q, r in ((hs, {"A": "R301", "B": "R305", "C": "R309"}[ph]), (ls, {"A": "R302", "B": "R306", "C": "R310"}[ph])):
            p.auto(r, gate(q), B, region=BOT_POWER)
    for r, c, ls in (("R304", "C301", "Q302"), ("R308", "C302", "Q304"), ("R312", "C303", "Q306")):
        p.auto(r, (ls, "5"), B, region=BOT_POWER)
        p.auto(c, (ls, "1"), B, region=BOT_POWER)
    # optional phase-voltage dividers (DNP on rev A), whole under the high-side source they tap: top
    # resistor turned so its divided (VPH) end faces the lower leg and the cap, away from the gate
    # resistor; the MCU's analog band keeps its room and no gate path is crossed
    for ph, top, lo, cap in (("A", "R313", "R314", "C313"), ("B", "R315", "R316", "C314"),
                             ("C", "R317", "R318", "C315")):
        x = LEGS[ph] - 1.9
        p.place(top, x, 8.55, rot=180, side="B")
        p.place(lo, x - 2.45, 8.55, rot=180, side="B")
        p.place(cap, x - 4.35, 8.55, rot=0, side="B")

    p.auto("TH301", ("Q304", "5"), B, region=BOT_POWER)

    M = lambda n: ("U401", str(n))  # noqa: E731
    up, right, down = (0.0, -1.0), (1.0, 0.0), (0.0, 1.0)

    def out(n, d, k=4.0):           # a point k mm beyond MCU pin n in direction d (where its track goes)
        x, y = p.pad_xy("U401", str(n))
        return (x + d[0] * k, y + d[1] * k)
    # ---- auto placement: (ref, near, side, toward) -------------------------------------------------------
    # `toward` is where the part's signal goes next: the part lands on that line, as near its pin as fits
    auto = [
        # VM / VDRAIN filters (10 Ω from V_BUS) at the top-left
        ("R201", (-8.5, -11.8), T, None), ("R202", (-8.5, -13.5), T, None),
        # 10 µF bulk behind the 10 Ω filters, together at the top-left next to the filter resistors
        ("C201", (-8.0, -13.6), T, None), ("C204", (-12.5, -13.6), T, None),
        ("C208", (6.5, -13.2), T, None), ("C209", ("U201", "26"), T, None), ("C210", ("U201", "26"), T, None),
        # buck (pins 42–48 on the top edge of the QFN)
        ("C211", (-3.0, -16.0), T, None), ("C212", (-3.0, -16.0), T, None),
        ("R203", ("U201", "47"), T, None), ("R204", ("U201", "46"), T, None), ("R205", ("U201", "48"), T, None),
        ("R206", ("U201", "48"), T, None),
        ("R207", ("L201", "2"), T, None), ("C213", ("L201", "2"), T, None), ("C214", ("L201", "2"), T, None),
        # ---- bottom: MCU decoupling, one cap at each supply pin, on the pin's own side
        ("C401", M(24), B, out(24, down)), ("C402", M(36), B, out(36, up)), ("C403", M(48), B, out(48, up)),
        ("C405", M(1), B, out(1, right)), ("C404", M(48), B, out(48, up, 6)),
        ("C408", M(20), B, out(20, down)), ("C407", M(21), B, out(21, down)), ("C406", M(21), B, out(21, down, 6)),
        ("FB101", M(21), B, out(21, down, 8)), ("C107", ("FB101", "2"), B, None), ("C108", ("FB101", "2"), B, None),
        # encoder (supply pins on the left, SPI on the right after the 180° turn): MISO's source resistor
        # right at its pin, before the MCU's analog parts fill the space between the two
        ("R501", ("U501", "5"), B, None), ("R502", ("U501", "8"), B, (2.86, 6.0)),
        ("C501", ("U501", "9"), B, (-6.0, 2.0)), ("C502", ("U501", "9"), B, (-6.0, 2.0)),
        ("D501", ("U501", "9"), B, (-6.0, 2.0)),
        # crystal straight out of PF0/PF1 to the right, its load caps beside it
        ("Y401", M(5), B, out(5, right, 6)), ("C409", ("Y401", "1"), B, None), ("C410", ("Y401", "3"), B, None),
        ("C411", M(7), B, out(7, right)), ("R401", M(45), B, out(45, up)),
        # current-sense RC (cap at the ADC pin, 100 Ω toward the DRV's SOx), SPI source resistors, pull-ups
        ("C412", M(18), B, out(18, down)), ("C413", M(16), B, out(16, down)), ("C414", M(17), B, out(17, down)),
        ("R404", M(18), B, ("U201", "25")), ("R405", M(16), B, ("U201", "24")), ("R406", M(17), B, ("U201", "23")),
        # CSA test points right at the SO side of their 100 Ω resistors (no long analog stubs)
        ("TP201", ("R404", "1"), B, None, dict(rots=(0, 90), radius=6.0, grow=(0.0, 0.0, 2.5, 0.0), region=CSA_TP)),
        ("TP202", ("R405", "1"), B, None, dict(rots=(0, 90), radius=6.0, grow=(0.0, 0.0, 2.5, 0.0), region=CSA_TP)),
        ("TP203", ("R406", "1"), B, None, dict(rots=(0, 90), radius=6.0, grow=(0.0, 0.0, 2.5, 0.0), region=CSA_TP)),
        ("R408", M(13), B, out(13, down)), ("R409", M(15), B, out(15, down)),
        ("R211", M(22), B, out(22, down, 6)), ("R210", M(14), B, out(14, down, 6)),
        ("TP208", ("R211", "2"), B, None, dict(rots=(0, 90), radius=14.0, grow=LABEL)),
        ("R209", M(25), B, out(25, down, 6)), ("R208", M(46), B, out(46, up)),
        # slow analog inputs on the right: cap at the pin, divider / pull-up toward the source
        ("C103", M(12), B, (17.0, 3.0)), ("R102", M(12), B, (17.0, 3.0)), ("R101", M(12), B, (17.0, 3.5)),
        ("C415", M(9), B, ("TH301", "1")), ("R407", M(9), B, ("TH301", "1")),
        ("C701", M(10), B, out(10, right)),
        # LED resistors at the MCU, on the way to their LEDs (top side)
        ("R403", M(2), B, ("D402", "1")), ("R402", M(3), B, ("D401", "1")),
        # CAN transceiver: supply caps at its pins, ESD and split termination toward the connectors
        ("C601", ("U601", "3"), B, None), ("C602", ("U601", "5"), B, None),
        ("D601", ("U601", "7"), B, ("J601", "2")), ("R601", ("U601", "7"), B, ("J601", "2")),
        ("R602", ("U601", "6"), B, ("J601", "3")), ("C603", ("U601", "6"), B, ("J601", "3")),
        ("JP601", ("U601", "7"), B, ("J601", "2")),
        # SW test point straight under the catch diode's cathode: a short stub (SW is the noisy node)
        ("TP207", ("D201", "1"), B, None, dict(rots=(0,), radius=6.0, grow=LABEL)),
        # aux: 47–100 Ω series at the MCU side, ESD array under the connector pins
        ("D701", ("J701", "3"), B, None), ("D702", ("J701", "6"), B, None),
        ("R701", M(39), B, ("J701", "2")), ("R702", M(40), B, ("J701", "3")), ("R703", M(41), B, ("J701", "4")),
        ("R704", M(42), B, ("J701", "5")), ("R705", M(44), B, ("J701", "6")),
        ("R706", ("D702", "2"), B, M(10)), ("R707", ("J701", "7"), B, None), ("JP701", ("J701", "8"), B, None),
        ("R708", ("J701", "2"), B, None), ("R709", ("J701", "6"), B, None), ("F701", ("J701", "1"), B, None),
        # LDO next to the CAN transceiver (both on +5V)
        ("U101", (-4.0, -11.0), B, None), ("C104", ("U101", "1"), B, None), ("C105", ("U101", "5"), B, None),
        ("C106", ("U101", "5"), B, None),
        # input TVS (2.3 mm tall SMC) under the XT30 region, close to its pins
        ("D101", ("J101", "2"), B, None), ("TP101", ("D101", "1"), B, None, dict(rots=(0,), radius=8.0, grow=LABEL)),
    ]
    for ref, near, side, toward, *kw in auto:
        opts = dict(region=TOP_LOGIC if side == T else BOT_LOGIC, toward=toward)
        opts.update(kw[0] if kw else {})
        p.auto(ref, near, side, **opts)

    # SWD pads (flat, bottom) at the top left, where the old MCU stood: SWD is slow and pogo pads need room
    p.auto("J401", (-8.0, -20.5), B, rots=(0, 90), radius=20.0)

    # low-side gate test points beside their gate resistors (GLx), the rest anywhere in the logic area
    for tp, rl in (("TP204", "R302"), ("TP205", "R306"), ("TP206", "R310")):
        p.auto(tp, (rl, "1"), B, region=Rect(-23, 9.5, 23, 23), rots=(0, 90), grow=LABEL)
    # the supply / GND test points go where their net already is (the centroid of its pads); the signal
    # ones sit beside the part they probe (above): a long stub is a routing problem, and on SW an antenna
    p.auto("TP105", ("FB101", "2"), B, rots=(0, 90), radius=10.0, region=CSA_TP, grow=LABEL)   # +3.3VA at its ferrite
    for tp in ("TP102", "TP103", "TP104", "TP106"):
        p.auto(tp, p.net_centroid(tp), B, rots=(0,), radius=32.0, region=BOT_LOGIC, grow=LABEL)
