"""Sheet 3 — DRV8353RS gate driver, charge pump, VDRAIN filter, LM5008A buck (+5V), logic interface."""
from gen.catalog import FP, PART, Kit
from gen.model import NC

from .layout import G, vert


def build(sch):
    sh = sch.sheet("driver.kicad_sch", "Gate driver and buck", page=3, ref_base=200)
    k = Kit(sh)

    # ---- the driver -------------------------------------------------------------------------
    u = sh.part("Tercio_B1:DRV8353RS", "DRV8353RSRGZR", (243.84, 139.7), fp=FP["RGZ48"],
                lcsc=PART["DRV8353RSRGZR"], mpn="DRV8353RSRGZR")
    left = {
        "VM": "VM_F", "VDRAIN": "VDRAIN", "VIN": "VBUS",
        "CPH": "CPH", "CPL": "CPL", "VCP": "VCP", "VGLS": "VGLS", "DVDD": "DVDD",
        "BST": "BST", "SW": "SW", "VCC": "VCC_BUCK", "FB": "BUCK_FB", "RT/SD": "RT_SD", "RCL": "RCL",
        "VREF": "+3.3VA",
        "ENABLE": "DRV_EN", "~{SCS}": "DRV_nCS", "SCLK": "SPI_SCK", "SDI": "SPI_MOSI", "SDO": "SPI_MISO",
        "~{FAULT}": "DRV_nFAULT",
        "INHA": "INHA", "INLA": "INLA", "INHB": "INHB", "INLB": "INLB", "INHC": "INHC", "INLC": "INLC",
    }
    for pin, net in left.items():
        u[pin] = net
    for ph in "ABC":
        u[f"GH{ph}"] = f"GH{ph}"
        u[f"SH{ph}"] = f"PHASE_{ph}"
        u[f"GL{ph}"] = f"GL{ph}"
        u[f"SP{ph}"] = f"SP_{ph}"
        u[f"SN{ph}"] = f"SN_{ph}"
        u[f"SO{ph}"] = f"SO{ph}"
    gpts = [u.wire_to(pin, "GND") for pin in ("GND", "AGND", "DGND", "PAD")]
    yb = gpts[0][1] + 5.08
    for x, y in gpts:
        sh.wire((x, y), (x, yb))
    sh.wire((gpts[0][0], yb), (gpts[-1][0], yb))
    for x, _ in gpts[1:-1]:
        sh.junction(x, yb)
    sh.power("GND", gpts[0][0], yb, 270)
    u.stub = 5.08

    # ---- supply, VDRAIN filter, charge pump ---------------------------------------------------------
    sh.box(20.32, 25.4, 205.74, 88.9, "Driver supply and charge pump (TI SLVSDY6A Table 21)")
    y = 55.88
    supply = [
        (k.R, "10", "0603", "VBUS", "VM_F"),       # VM filter: keeps spikes off the 80 V-abs VM pin
        (k.C, "10u", "1210", "VM_F", "GND"),      # VM local ≥ 10 µF (Table 21)
        (k.C, "100n", "0603", "VM_F", "GND"),     # VM HF bypass, at pin 5
        (k.C, "1u", "0805", "VBUS", "GND"),       # VIN (buck input), at pin 43
        (k.R, "10", "0603", "VBUS", "VDRAIN"),    # VDRAIN slew limit (see note)
        (k.C, "10u", "1210", "VDRAIN", "GND"),
        (k.C, "47n", "0603", "CPH", "CPL"),       # flying cap, VDRAIN-rated
        (k.C, "1u", "0603", "VCP", "VDRAIN"),     # charge-pump storage
        (k.C, "1u", "0603", "VGLS", "GND"),       # low-side gate supply (14.5 V)
        (k.C, "1u", "0402", "DVDD", "GND"),       # internal 5 V logic
        (k.C, "1u", "0402", "+3.3VA", "GND"),     # VREF (CSA bias = VREF/2)
        (k.C, "100n", "0402", "+3.3VA", "GND"),
    ]
    for i, (fn, val, pkg, top, bot) in enumerate(supply):
        vert(fn(val, (30.48 + i * 15.24, y), pkg=pkg), top, bot)
    k.flag("VM_F", (203.2, 43.18))
    sh.note(22.86, 71.12,
            "VDRAIN: 10 Ω + 10 µF (≈ 4 µF at 48 V → τ ≈ 40 µs) keeps the slew under the 2 V/µs abs max on hot-plug.\n"
            "VDRAIN also carries the charge-pump current (1.9 mA + 3·Qg·f ≈ 9 mA @ 30 kHz, 16 mA @ 60 kHz) → drop ≤ 0.16 V;\n"
            "subtract it from the high-side VDS_LVL. VM: 10 Ω + 10 µF filter (~25–35 mA → ≤ 0.35 V), 9–75 V operating.", size=1.27)

    # ---- buck: LM5008A inside the DRV8353R --------------------------------------------------------------
    sh.box(20.32, 96.52, 205.74, 182.88, "+5V buck — integrated LM5008A (COT, 350 mA), ≈ 180 kHz")
    y1, y2 = 127.0, 160.02
    vert(k.R("200k", (33.02, y1), pkg="0603"), "VBUS", "RT_SD")                       # RT: Ton = 1.385e-10·RT/VIN
    vert(k.R("150k", (45.72, y1), pkg="0603"), "RCL", "GND")                          # current-limit off-time
    vert(k.C("470n", (58.42, y1), pkg="0603"), "VCC_BUCK", "GND")                     # 7 V bias regulator
    vert(k.C("10n", (71.12, y1), pkg="0402"), "BST", "SW")                            # bootstrap
    d = sh.part("Device:D_Schottky", "MBR1H100SFT3G", (86.36, y1), rot=270, fp=FP["SOD123F"], lcsc=PART["MBR1H100SFT3G"],
                mpn="MBR1H100SFT3G")
    d["K"] = "SW"; d["A"] = "GND"
    l = sh.part("Device:L", "100µH", (101.6, y1), fp=FP["L6045"], lcsc=PART["SWPA6045S101MT"], mpn="SWPA6045S101MT")
    vert(l, "SW", "BUCK_L")
    vert(k.R("4.7k", (33.02, y2)), "BUCK_L", "BUCK_FB")                              # FB divider: 2.5 V × (4.7k+4.7k)/4.7k = 5.0 V
    vert(k.R("4.7k", (45.72, y2)), "BUCK_FB", "GND")
    r = k.R("1", (60.96, y2), rot=180, pkg="0805")                                    # ripple resistor (Fig. 51)
    r[1] = "BUCK_L"; r[2] = "+5V"
    vert(k.C("22u", (76.2, y2), pkg="0805"), "+5V", "GND")
    vert(k.C("100n", (88.9, y2)), "+5V", "GND")
    f = sh.part("power:PWR_FLAG", "PWR_FLAG", (101.6, y2 - 2.54), rot=0, ref="#FLG")
    f[1] = "+5V"
    sh.note(114.3, 104.14,
            "LM5008A design (VIN 10–52 V, VOUT ≈ 5.0 V, ≤ 250 mA):\n"
            "• RT = 200k → Ton = 0.53 µs @ 52 V (> 400 ns min), f ≈ 5 V / (1.385e-10 × RT) ≈ 180 kHz\n"
            "• L = 100 µH, 1 A sat: ΔI = 0.14 A @ 10 V … 0.25 A @ 52 V; guaranteed load ≈ 0.25 A (I_LIM min 0.41 A)\n"
            "• FB node = 2.5 × (4.7k + 4.7k)/4.7k = 5.0 V; R = 1 Ω gives FB ripple 70–125 mV (≥ 25 mV needed)\n"
            "  and +5V = 5.0 − 1 Ω × I_load (≈ 4.8 V @ 200 mA; ≤ 5.4 V worst case at light load)\n"
            "• RCL = 150k → T_off ≈ 3.4 µs in overload; 35 µs in short circuit\n"
            "• D = MBR1H100SFT3G (100 V, 1 A, 0.76 V, SOD-123FL: the buck pins need the room an SMA took)", size=1.27)

    # ---- logic interface ----------------------------------------------------------------------------------------
    sh.box(20.32, 190.5, 205.74, 254.0, "Logic interface — pulls keep the driver safe while the MCU is in reset")
    y3 = 218.44
    vert(k.R("100k", (33.02, y3)), "DRV_EN", "GND")         # ENABLE low = sleep, bridge off
    vert(k.R("10k", (50.8, y3)), "+3V3", "DRV_nCS")          # deselect during reset
    vert(k.R("1.5k", (68.58, y3)), "+3V3", "SPI_MISO")       # SDO is open-drain; shared MISO with the MT6835
    vert(k.R("10k", (86.36, y3)), "+3V3", "DRV_nFAULT")      # nFAULT open-drain → TIM1_BKIN
    sh.note(101.6, 205.74,
            "SPI: mode 1, ≤ 10 MHz (MT6835 shares SCK/MOSI/MISO in mode 3; the ISR owns SPI1).\n"
            "SDO pull-up 1.5k (~25 ns at 15 pF); run DRV transactions ≤ 4 MHz, then restore CPOL = 1 for the MT6835.\n"
            "6×PWM mode (PWM_MODE = 00b). INHx/INLx have internal pull-downs.\n"
            "CSA gain per motor profile over SPI: ×40 gimbal (±35 A), ×10 QDD (±140 A, 1 mΩ).\n"
            "CSA offset ±3 mV max → calibrate (CAL bits) at every enable.", size=1.27)

    # ---- bring-up test points (docs/08-bringup.md stages 3–6) ------------------------------------------------
    sh.box(279.4, 190.5, 403.86, 238.76, "Bring-up test points — scope probes with a ground spring")
    for i, net in enumerate(("SOA", "SOB", "SOC", "GLA", "GLB", "GLC", "SW", "DRV_nFAULT")):
        t = k.tp(net, (289.56 + i * 13.97, 203.2))
        t[1] = net
    return sh
