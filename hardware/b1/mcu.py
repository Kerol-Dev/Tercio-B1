"""Sheet 5 — STM32G431CBT6: supplies, clock, reset/boot, SWD, LEDs, ADC front-end, SPI source termination."""
from gen.catalog import FP, PART, Kit
from gen.model import NC

from .layout import G, rc_lowpass, vert

# Pin map: docs/04-architecture.md §4.2 (data/pinmap-g431cbt6.csv)
PINMAP = {
    "PC13": "LED_FAULT", "PC14": "LED_STATUS", "PC15": "ENC_CAL",
    "PF0": "OSC_IN", "PF1": "OSC_OUT", "PG10": "NRST",
    "PA0": "VPH_B", "PA1": "NTC_FET", "PA2": "AUX_ANA", "PA3": "VPH_C", "PA4": "VBUS_SENSE",
    "PA5": "SPI_SCK_MCU", "PA6": "SPI_MISO", "PA7": "SPI_MOSI_MCU",
    "PB0": "ADC_IB", "PB1": "ADC_IC", "PB2": "ADC_IA",
    "PB10": "DRV_nFAULT", "PB11": "DRV_nCS", "PB12": "VPH_A",
    "PB13": "INLA", "PB14": "INLB", "PB15": "INLC",
    "PA8": "INHA", "PA9": "INHB", "PA10": "INHC",
    "PA11": "CAN_RXD", "PA12": "CAN_TXD", "PA13": "SWDIO", "PA14": "SWCLK",
    "PA15": "AUX1", "PB3": "AUX2", "PB4": "AUX3", "PB5": "AUX4", "PB6": "ENC_nCS", "PB7": "AUX5",
    "PB8": "BOOT0", "PB9": "DRV_EN",
}


def build(sch):
    sh = sch.sheet("mcu.kicad_sch", "MCU", page=5, ref_base=400)
    k = Kit(sh)

    X, Y = 215.9, 152.4
    u = sh.part("MCU_ST_STM32G4:STM32G431CBTx", "STM32G431CBT6", (X, Y), fp=FP["LQFP48"],
                lcsc=PART["STM32G431CBT6"], mpn="STM32G431CBT6")
    for pin, net in PINMAP.items():
        u[pin] = net
    u["VREF+"] = "+3.3VA"
    u.stub = 5.08
    # supplies: VBAT + 3 × VDD on one +3V3 bus, VDDA alone, VSS/VSSA joined
    ytop = Y - 40.64
    pts = [u.wire_to(n, "+3V3") for n in ("1", "24", "36", "48")]
    for x, y in pts:
        sh.wire((x, y), (x, ytop - 5.08))
    sh.wire((pts[0][0], ytop - 5.08), (pts[-1][0], ytop - 5.08))
    for x, _ in pts[1:-1]:
        sh.junction(x, ytop - 5.08)
    sh.wire((pts[0][0], ytop - 5.08), (pts[0][0], ytop - 10.16))
    sh.junction(pts[0][0], ytop - 5.08)
    sh.power("+3V3", pts[0][0], ytop - 10.16, 90)
    vdda = u.wire_to("VDDA", "+3.3VA")
    sh.wire(vdda, (vdda[0], ytop - 10.16))
    sh.power("+3.3VA", vdda[0], ytop - 10.16, 90)
    vss, vssa = u.wire_to("23", "GND"), u.wire_to("VSSA", "GND")
    ybot = Y + 40.64 + 5.08
    sh.wire(vss, (vss[0], ybot)); sh.wire(vssa, (vssa[0], ybot)); sh.wire((vss[0], ybot), (vssa[0], ybot))
    sh.power("GND", vss[0], ybot, 270)
    sh.note(X + 22.86, Y + 43.18, "VSS 35/47 are stacked\nwith VSS 23 in the symbol.", size=1.27)

    # ---- decoupling ------------------------------------------------------------------------------------
    sh.box(152.4, 25.4, 289.56, 88.9, "Supply decoupling — one 100 nF per VDD pin, at the pin")
    y = 63.5
    for i in range(3):
        vert(k.C("100n", (165.1 + i * 15.24, y)), "+3V3", "GND")
    vert(k.C("4.7u", (210.82, y), pkg="0603"), "+3V3", "GND")
    vert(k.C("100n", (226.06, y)), "+3V3", "GND")                     # VBAT
    vert(k.C("1u", (246.38, y)), "+3.3VA", "GND")                     # VDDA / VREF+
    vert(k.C("10n", (261.62, y)), "+3.3VA", "GND")
    vert(k.C("100n", (276.86, y)), "+3.3VA", "GND")

    # ---- clock ---------------------------------------------------------------------------------------------
    sh.box(20.32, 25.4, 139.7, 88.9, "16 MHz HSE — same crystal as S1/FD (CL 9 pF)")
    xt = sh.part("Device:Crystal_GND24", "16MHz", (63.5, 50.8), fp=FP["XTAL3225"], lcsc=PART["X322516MLB4SI"],
                 mpn="X322516MLB4SI", ref="Y")
    xt[1] = "OSC_IN"; xt[3] = "OSC_OUT"; xt[2] = "GND"
    xt.stub = 5.08
    vert(k.C("12p", (40.64, 66.04)), "OSC_IN", "GND")
    vert(k.C("12p", (86.36, 66.04)), "OSC_OUT", "GND")
    sh.note(96.52, 40.64, "C_L = 9 pF → 2 × (9 − ~3 pF stray)\n= 12 pF C0G. HSE checked against\nHSI at boot (board/Clock.cpp).", size=1.27)

    # ---- reset, boot, SWD ------------------------------------------------------------------------------------------
    sh.box(20.32, 101.6, 139.7, 177.8, "Reset, BOOT0 and SWD (1×5 pads, S1/FD order)")
    j = sh.part("Connector_Generic:Conn_01x05", "SWD", (53.34, 139.7), rot=180, fp=FP["SWDPADS"], ref="J")
    j.in_bom = False  # bare pads on the bottom: pogo adapter or soldered wires
    j[1] = "+3V3"; j[2] = "SWDIO"; j[3] = "SWCLK"; j[4] = "NRST"; j[5] = "GND"
    j.stub = 5.08
    vert(k.C("100n", (96.52, 132.08)), "NRST", "GND")                  # ST: 100 nF on NRST (missing on S1)
    vert(k.R("10k", (116.84, 132.08)), "BOOT0", "GND")                 # BOOT0 pull-down (S1/FD lesson)
    sh.note(83.82, 152.4, "PB8-BOOT0: 10k to GND, never a\nsignal pin. Option bytes keep\nnBOOT0 = 1, nSWBOOT0 = 0.", size=1.27)

    # ---- LEDs ---------------------------------------------------------------------------------------------------------
    sh.box(20.32, 190.5, 139.7, 254.0, "Status LEDs (PC13/PC14 sink ≤ 3 mA)")
    for i, (net, color, part, supply, r) in enumerate((
            ("LED_STATUS", "green", "KT-0805G", "+5V", "2.2k"),
            ("LED_FAULT", "red", "KT-0603R", "+3V3", "1k"))):
        y = 213.36 + i * 20.32
        rr = k.R(r, (45.72, y), rot=90)
        rr[1] = net
        rr.stub = 5.08
        kpt = rr.wire_to(2, f"{net}_K")
        led = sh.part("Device:LED", color, (kpt[0] + 3.81, y), fp=FP["LED0805" if color == "green" else "LED0603"],
                      lcsc=PART[part], mpn=part, ref="D")
        led.wire_to("K", f"{net}_K")
        led["A"] = supply
    sh.note(83.82, 208.28, "Green from +5V: V_F ≈ 2.9 V needs\nmore than 3.3 V headroom; off-state\nleaves the pin ≤ 3.3 V.", size=1.27)

    # ---- ADC front-end -----------------------------------------------------------------------------------------------
    sh.box(304.8, 25.4, 403.86, 132.08, "ADC front-end — CSA outputs, NTC")
    for i, ph in enumerate("ABC"):
        rc_lowpass(k, 322.58, 45.72 + i * 22.86, f"SO{ph}", f"ADC_I{ph}", "100", "1n")
    sh.note(309.88, 111.76, "100 Ω + 1 nF: τ = 100 ns ≪ CSA settling (0.25–2 µs);\nisolates the CSA output from the ADC sample cap.", size=1.27)
    yn = 152.4
    rn = k.R("10k", (322.58, yn))
    rn[1] = "+3.3VA"
    p = rn.wire_to(2, "NTC_FET")
    cn = k.C("100n", (335.28, yn + 11.43))
    t = cn.wire_to(1, "NTC_FET")
    cn[2] = "GND"
    sh.wire(p, (322.58, yn + 5.08)); sh.wire((322.58, yn + 5.08), (335.28, yn + 5.08), t)
    sh.wire((335.28, yn + 5.08), (342.9, yn + 5.08)); sh.junction(335.28, yn + 5.08)
    sh.label("NTC_FET", 342.9, yn + 5.08, 0)

    # ---- SPI source termination --------------------------------------------------------------------------------------
    sh.box(304.8, 177.8, 403.86, 228.6, "SPI1 source termination (encoder + driver)")
    for i, (a, b) in enumerate((("SPI_SCK_MCU", "SPI_SCK"), ("SPI_MOSI_MCU", "SPI_MOSI"))):
        r = k.R("22", (342.9, 195.58 + i * 12.7), rot=90)
        r[1] = a; r[2] = b
        r.stub = 5.08
    sh.note(309.88, 220.98, "MISO is terminated at the MT6835 (encoder sheet).", size=1.27)
    return sh
