"""Sheet 2 — power input (XT30, TVS, bulk), bus-voltage sense, 3.3 V and analog rails."""
from gen.catalog import FP, PART, Kit
from gen.model import NC

from .layout import G, column, divider, rail, vert


def build(sch):
    sh = sch.sheet("power.kicad_sch", "Power input and rails", page=2, ref_base=100)
    k = Kit(sh)

    # ---- power input -------------------------------------------------------------------
    sh.box(20.32, 25.4, 177.8, 109.22, "Power input — XT30, 10–52 V (OV fault ≤ 58 V)")
    yv, yg = 50.8, 93.98  # VBUS and GND rails
    j = sh.part("Connector_Generic:Conn_01x02", "XT30PW-M", (30.48, 66.04), rot=180, fp=FP["XT30PW"],
                lcsc=PART["XT30PW-M"], mpn="XT30PW-M30.G.Y")
    p_pos = j.wire_to(2, "VBUS")  # XT30PW-M footprint: pad 2 = "+", pad 1 = "−"
    p_neg = j.wire_to(1, "GND")
    sh.wire(p_pos, (40.64, p_pos[1]), (40.64, yv))
    sh.wire(p_neg, (38.1, p_neg[1]), (38.1, yg))
    sh.power("VBUS", 48.26, yv, 90)
    sh.power("GND", 48.26, yg, 270)

    xs_v, xs_g = [40.64, 48.26], [38.1, 48.26]
    tvs = sh.part("Device:D_Zener", "SMCJ54A", (60.96, 72.39), rot=270, fp=FP["SMC"], lcsc=PART["SMCJ54A"],
                  mpn="SMCJ54A", ref="D")
    for part, x in ((tvs, 60.96),):
        top, bot = part.wire_to("K", "VBUS"), part.wire_to("A", "GND")
        sh.wire(top, (x, yv)); sh.wire(bot, (x, yg)); xs_v.append(x); xs_g.append(x)
    ce = sh.part("Device:C_Polarized", "22µF 100V", (76.2, 72.39), fp=FP["CP6.3x7.7"], lcsc=PART["JVJ100V22M6x8"],
                 mpn="JVJ100V22M6x8")
    cm = k.C("10u", (91.44, 72.39), pkg="1210")
    for part, x in ((ce, 76.2), (cm, 91.44)):
        top, bot = part.wire_to(1, "VBUS"), part.wire_to(2, "GND")
        sh.wire(top, (x, yv)); sh.wire(bot, (x, yg)); xs_v.append(x); xs_g.append(x)
    for net, x, rot in (("VBUS", 104.14, 180), ("GND", 116.84, 0)):
        f = sh.part("power:PWR_FLAG", "PWR_FLAG", (x, yv - 5.08 if net == "VBUS" else yg + 5.08), rot=0 if net == "VBUS" else 180, ref="#FLG")
        pt = f.wire_to(1, net)
        y = yv if net == "VBUS" else yg
        sh.wire(pt, (x, y)); (xs_v if net == "VBUS" else xs_g).append(x)
    tpv = k.tp("VBUS", (127.0, yv - 5.08), rot=0)
    sh.wire(tpv.wire_to(1, "VBUS"), (127.0, yv)); xs_v.append(127.0)
    tpg = k.tp("GND", (127.0, yg + 5.08), rot=180)
    sh.wire(tpg.wire_to(1, "GND"), (127.0, yg)); xs_g.append(127.0)
    xs_v.append(142.24)  # divider tap
    rail(sh, yv, xs_v)
    rail(sh, yg, xs_g)

    # bus-voltage sense: 100k / 5.1k -> 60 V full scale ≈ 2.91 V, 1 nF (τ ≈ 4.9 µs)
    sh.wire((142.24, yv), (142.24, 59.69))
    divider(k, 142.24, 63.5, "VBUS", "VBUS_SENSE", "GND", "100k", "5.1k", pkg_top="0603", cap="1n", top_wired=True)
    sh.note(142.24, 99.06, "V_BUS sense: 100k/5.1k → 20.6:1\n0–60 V → 0–2.91 V (ADC2_IN12)", size=1.27)

    # ---- 3.3 V LDO --------------------------------------------------------------------------
    sh.box(20.32, 121.92, 177.8, 200.66, "Logic rails — +5V (driver buck) → +3V3 LDO → +3.3VA (filtered)")
    y = 152.4
    u = sh.part("Regulator_Linear:TLV75533PDBV", "TLV75533PDBVR", (88.9, y + 2.54), fp=FP["SOT23_5"],
                lcsc=PART["TLV75533PDBVR"], mpn="TLV75533PDBVR")
    pin_in, pin_en, pin_out = u.wire_to("IN", "+5V"), u.wire_to("EN", "+5V"), u.wire_to("OUT", "+3V3")
    u["GND"] = "GND"
    sh.power("+5V", 45.72, y, 90)
    cin = k.C("1u", (63.5, y + 6.35))
    sh.wire((45.72, y), (63.5, y)); sh.wire((63.5, y), (73.66, y)); sh.wire((73.66, y), pin_in)
    sh.junction(63.5, y); sh.junction(73.66, y)
    sh.wire(cin.wire_to(1, "+5V"), (63.5, y)); cin[2] = "GND"
    sh.wire(pin_en, (73.66, pin_en[1]), (73.66, y))
    c1 = k.C("4.7u", (106.68, y + 6.35), pkg="0603")
    c2 = k.C("100n", (121.92, y + 6.35))
    sh.wire(pin_out, (106.68, y), (121.92, y), (134.62, y))
    sh.junction(106.68, y); sh.junction(121.92, y)
    for c, x in ((c1, 106.68), (c2, 121.92)):
        sh.wire(c.wire_to(1, "+3V3"), (x, y)); c[2] = "GND"
    sh.power("+3V3", 134.62, y, 90)

    # analog rail: ferrite + 1 µF + 10 nF; feeds VDDA/VREF+ and the DRV8353 VREF (ratiometric sensing)
    fb = sh.part("Device:FerriteBead_Small", "600Ω@100MHz", (137.16, y + 22.86), rot=90, fp=FP["FB0603"],
                 lcsc=PART["GZ1608D601TF"], mpn="GZ1608D601TF", ref="FB")
    a, b = fb.wire_to(1, "+3V3"), fb.wire_to(2, "+3.3VA")
    ya = y + 22.86
    sh.power("+3V3", 124.46, ya, 90)
    sh.wire((124.46, ya), a)
    ca1 = k.C("1u", (149.86, ya + 6.35))
    ca2 = k.C("10n", (162.56, ya + 6.35))
    sh.wire(b, (149.86, ya), (162.56, ya), (172.72, ya))
    sh.junction(149.86, ya); sh.junction(162.56, ya)
    for c, x in ((ca1, 149.86), (ca2, 162.56)):
        sh.wire(c.wire_to(1, "+3.3VA"), (x, ya)); c[2] = "GND"
    sh.power("+3.3VA", 172.72, ya, 90)
    fa = sh.part("power:PWR_FLAG", "PWR_FLAG", (172.72, ya + 7.62), rot=180, ref="#FLG")
    sh.wire(fa.wire_to(1, "+3.3VA"), (172.72, ya))
    sh.note(25.4, 190.5, "+5V comes from the DRV8353R buck (driver sheet), ≤ 250 mA budget.\n"
                         "+3V3: MCU, MT6835, CAN VIO, aux 3V3 (PTC-limited). +3.3VA: VDDA, VREF+, DRV VREF, NTC pull-ups.")

    # ---- test points and mounting --------------------------------------------------------------
    sh.box(190.5, 25.4, 279.4, 109.22, "Test points and mounting")
    for i, net in enumerate(("+5V", "+3V3", "+3.3VA")):
        t = k.tp(net, (203.2 + i * 15.24, 55.88), rot=180)
        t[1] = net
    tg = k.tp("GND", (248.92, 55.88))
    tg[1] = "GND"
    for i in range(4):
        h = sh.part("Mechanical:MountingHole", "M2.5", (203.2 + i * 15.24, 83.82), fp=FP["HOLE_M25"], ref="H")
        h.in_bom = False
    sh.note(193.04, 96.52, "Holes isolated from GND (no ground loop through the motor frame).")

    # ---- design notes ---------------------------------------------------------------------------------
    sh.note(190.5, 121.92,
            "Power-input notes\n"
            "• 80 V FETs, 100 V MLCCs, 100 V electrolytic: ≥ 1.5× headroom at 52 V.\n"
            "• SMCJ54A (1.5 kW): 54 V standoff, 60 V breakdown — catches hot-plug ringing, not regen.\n"
            "  The DRV8353 VM pin (80 V abs max) also sits behind a 10 Ω + 10 µF filter (driver sheet).\n"
            "• Regen is limited in firmware (MaxRegenCurrent, OV clamp); bench: e-load in CV mode.\n"
            "• Recommend an anti-spark connector (XT90-S) or precharge on the battery side.\n"
            "• 22 µF 100 V electrolytic (6.3 × 7.7 mm) damps the supply-cable resonance on hot-plug.",
            size=1.524)
    return sh
