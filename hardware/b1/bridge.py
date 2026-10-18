"""Sheet 4 — power stage: three half-bridges, Kelvin shunts, bulk capacitance, FET NTC, phase-voltage taps."""
from gen.catalog import FP, PART, Kit

from .layout import G, column, divider, rail, vert

LEG_X = (71.12, 152.4, 233.68)  # drain line x of each leg
Y_VBUS, Y_GND = 40.64, 205.74
Y_HS, Y_LS, Y_PH, Y_SH = 71.12, 121.92, 96.52, 157.48


def build(sch):
    sh = sch.sheet("bridge.kicad_sch", "Power stage", page=4, ref_base=300)
    k = Kit(sh)
    vbus_x, gnd_x = [25.4], [25.4]
    sh.power("VBUS", 25.4, Y_VBUS, 90)
    sh.power("GND", 25.4, Y_GND, 270)

    for ph, xd in zip("ABC", LEG_X):
        xq = xd - 2.54  # FET symbol origin: drain/source pins are 2.54 right of it
        hs = sh.part("Transistor_FET:BSC030N08NS5", "BSC030N08NS5", (xq, Y_HS), fp=FP["TDSON8"],
                     lcsc=PART["BSC030N08NS5"], mpn="BSC030N08NS5")
        ls = sh.part("Transistor_FET:BSC030N08NS5", "BSC030N08NS5", (xq, Y_LS), fp=FP["TDSON8"],
                     lcsc=PART["BSC030N08NS5"], mpn="BSC030N08NS5")
        d_hs = hs.wire_to("D", "VBUS")
        s_hs = hs.wire_to(1, f"PHASE_{ph}")
        d_ls = ls.wire_to("D", f"PHASE_{ph}")
        s_ls = ls.wire_to(1, f"LSRC_{ph}")
        # drain to the VBUS rail, phase node, low-side source to the shunt
        sh.wire(d_hs, (xd, Y_VBUS)); vbus_x.append(xd)
        sh.wire(s_hs, (xd, Y_PH)); sh.wire((xd, Y_PH), d_ls); sh.junction(xd, Y_PH)
        # phase node out to the motor pad, labelled for the driver (SHx) and the voltage tap
        xp = xd + 15.24
        sh.wire((xd, Y_PH), (xp, Y_PH)); sh.wire((xp, Y_PH), (xd + 30.48, Y_PH))
        sh.label(f"PHASE_{ph}", xp, Y_PH, 0)
        pad = sh.part("Connector_Generic:Conn_01x01", f"MOTOR {ph}", (xd + 35.56, Y_PH), fp=FP["MOTORPAD"], ref="J")
        pad.in_bom = False  # bare plated pad
        sh.wire((xd + 30.48, Y_PH), pad.wire_to(1, f"PHASE_{ph}"))
        # gate resistors (0 Ω, tune IDRIVE first; footprints allow a series R if ringing needs it)
        for fet, gnet, y in ((hs, f"GH{ph}", Y_HS), (ls, f"GL{ph}", Y_LS)):
            rg = k.R("0", (xq - 5.08 - 3.81, y), rot=90)
            rg[1] = gnet
            rg.stub = 5.08
            rg.wire_to(2, f"G_{ph}{'H' if fet is hs else 'L'}")
            fet.wire_to("G", f"G_{ph}{'H' if fet is hs else 'L'}")  # pins coincide
        # Kelvin shunt: pin 1/4 carry current, 2/3 are the sense taps
        rs = sh.part("Device:R_Shunt", "1mΩ 3W", (xd, Y_SH), fp=FP["SHUNT2512K"], lcsc=PART["RLP25FEGR001"],
                     mpn="RLP25FEGR001", ref="R")
        top = rs.wire_to(1, f"LSRC_{ph}")
        bot = rs.wire_to(4, "GND")
        rs[2] = f"SP_{ph}"
        rs[3] = f"SN_{ph}"
        rs.stub = 5.08
        sh.wire(s_ls, (xd, 139.7)); sh.wire((xd, 139.7), top)
        sh.wire((xd, 139.7), (xd - 7.62, 139.7)); sh.junction(xd, 139.7)
        sh.label(f"LSRC_{ph}", xd - 7.62, 139.7, 180)
        sh.wire(bot, (xd, Y_GND)); gnd_x.append(xd)
        # RC snubber across the low-side FET — not fitted on rev A
        rsn = k.R("4.7", (xd + 15.24, 121.92), pkg="0805", dnp=True)
        csn = k.C("1n", (xd + 15.24, 137.16), pkg="0603", dnp=True)
        csn.value = "1nF 100V"
        a = rsn.wire_to(2, f"SNUB_{ph}"); b = csn.wire_to(1, f"SNUB_{ph}")
        sh.wire(a, b)
        rsn[1] = f"PHASE_{ph}"
        csn[2] = f"LSRC_{ph}"

    # ---- bulk and HF capacitance (place 3 + 1 per leg at layout) ---------------------------------------
    rail(sh, Y_VBUS, vbus_x)
    rail(sh, Y_GND, gnd_x)
    sh.box(284.48, 25.4, 401.32, 152.4, "Bulk and HF bypass, V_BUS to GND")
    for i in range(9):
        x, y = 294.64 + (i % 6) * 17.78, (63.5, 106.68)[i // 6]
        if i < 6:
            vert(k.C("10u", (x, y), pkg="1210"), "VBUS", "GND")
        else:
            vert(k.C("100n", (x, y), pkg="0805"), "VBUS", "GND")
    sh.note(287.02, 129.54, "Bulk: 6 × 10 µF 100 V X7R 1210 + 3 × 100 nF 100 V here, + C102 (10 µF) and the 22 µF 100 V can on the\n"
                          "power sheet; ~28 µF effective MLCC at 48 V DC bias. Slots beside each leg at layout.", size=1.27)

    # ---- FET temperature ----------------------------------------------------------------------------------------
    sh.box(20.32, 215.9, 76.2, 274.32, "FET temperature")
    th = sh.part("Device:Thermistor_NTC", "10k B3434", (33.02, 246.38), fp=FP["R0603"],
                 lcsc=PART["NCP18XH103F03RB"], mpn="NCP18XH103F03RB", ref="TH")
    vert(th, "NTC_FET", "GND")
    sh.note(43.18, 228.6, "Between the\nlow-side FETs;\npull-up on the\nMCU sheet.", size=1.27)

    # ---- phase-voltage taps (not fitted on rev A) ----------------------------------------------------------------
    sh.box(88.9, 215.9, 254.0, 274.32, "Phase-voltage taps — DNP on rev A (sensorless / flying start / phase-loss)")
    for i, ph in enumerate("ABC"):
        divider(k, 101.6 + i * 50.8, 243.84, f"PHASE_{ph}", f"VPH_{ph}", "GND", "100k", "5.1k",
                pkg_top="0603", cap="1n", dnp=True)

    sh.note(287.02, 160.02,
            "Power-stage notes\n"
            "• Q: BSC030N08NS5, 80 V, 3.0 mΩ, Qg 76 nC, SuperSO8.\n"
            "• Shunts 1 mΩ: 15 A RMS → 0.23 W; 80 A burst → 6.4 W (check pulse curve).\n"
            "• CSA input range ±0.3 V diff, ±0.15 V common mode.\n"
            "• Kelvin: SP_x/SN_x run as a pair from the shunt pads\n"
            "  to the DRV, never shared with the power path.\n"
            "• SHx = PHASE_x: dedicated trace to the HS source.", size=1.27)
    return sh
