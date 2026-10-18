"""Sheets 6–8 — MT6835 encoder, CAN-FD, aux connector."""
from gen.catalog import FP, PART, Kit
from gen.model import NC

from .layout import G, vert


def encoder(sch):
    sh = sch.sheet("encoder.kicad_sch", "Encoder", page=6, ref_base=500)
    k = Kit(sh)
    sh.box(50.8, 40.64, 254.0, 160.02, "MT6835 21-bit magnetic encoder — bottom side, on the shaft axis")
    u = sh.part("Tercio_B1:MT6835", "MT6835GT-STD-R", (139.7, 101.6), fp=FP["TSSOP16"], lcsc=PART["MT6835GT-STD-R"],
                mpn="MT6835GT-STD-R")
    u.connect(CSN="ENC_nCS", SCK="SPI_SCK", MOSI="SPI_MOSI", CAL_EN="ENC_CAL", TEST_EN="GND", VDD="+3V3", VSS="GND")
    u["MISO"] = "ENC_MISO"
    u["TEST"] = "GND"  # reference circuits tie pins 11 and 13 to VSS
    for pin in ("A", "B", "Z", "U", "V", "W", "OUT"):
        u[pin] = NC
    u.stub = 5.08
    r = k.R("22", (101.6, 127.0), rot=90)                     # MISO source termination, at the encoder
    r[1] = "SPI_MISO"; r[2] = "ENC_MISO"
    r.stub = 5.08
    vert(k.R("10k", (76.2, 66.04)), "+3V3", "ENC_nCS")        # deselected while the MCU is in reset
    vert(k.C("100n", (190.5, 76.2)), "+3V3", "GND")           # ≥ 100 nF at VDD (datasheet §7.2)
    vert(k.C("1u", (208.28, 76.2)), "+3V3", "GND")
    tvs = sh.part("Device:D_TVS", "PESD5V0S1BA", (228.6, 76.2), rot=270, fp=FP["SOD323"], lcsc=PART["PESD5V0S1BA"],
                  mpn="PESD5V0S1BA", ref="D")
    tvs[1] = "+3V3"; tvs[2] = "GND"                           # datasheet recommends a TVS on VDD for EMC
    sh.note(162.56, 116.84,
            "SPI mode 3, ≤ 16 MHz; burst read returns ANGLE[20:0], STATUS[2:0], CRC8 (x⁸+x²+x+1).\n"
            "CAL_EN (pin 4) low→high while spinning at constant speed runs the on-chip self-calibration\n"
            "(INL ±0.07° typ.); driven from PC15. TEST and TEST_EN tied to VSS (datasheet Fig. 5/6).\n"
            "Place on the board centre (shaft axis), no copper pours under the sensor, magnet gap per motor.",
            size=1.27)
    return sh


def can(sch):
    sh = sch.sheet("can.kicad_sch", "CAN-FD", page=7, ref_base=600)
    k = Kit(sh)
    sh.box(30.48, 40.64, 330.2, 172.72, "CAN-FD — MCP2562FD (same as the FD adapter), 2 × JST-GH 4 daisy chain")
    u = sh.part("Interface_CAN_LIN:MCP2562-E-SN", "MCP2562FDT-E/SN", (101.6, 101.6), fp=FP["SOIC8"],
                lcsc=PART["MCP2562FDT-E/SN"], mpn="MCP2562FDT-E/SN")
    u.connect(TXD="CAN_TXD", RXD="CAN_RXD", VDD="+5V", VSS="GND", Vio="+3V3", STBY="GND", CANH="CANH", CANL="CANL")
    u.stub = 5.08
    vert(k.C("100n", (60.96, 66.04)), "+5V", "GND")
    vert(k.C("100n", (78.74, 66.04)), "+3V3", "GND")
    sh.note(38.1, 129.54, "STBY tied low: always active (internal pull-up would\nhold it in standby). VIO = 3.3 V logic levels.", size=1.27)

    esd = sh.part("Power_Protection:NUP2105L", "NUP2105LT1G", (152.4, 121.92), fp=FP["SOT23"], lcsc=PART["NUP2105LT1G"],
                  mpn="NUP2105LT1G", ref="D")
    esd[1] = "CANH"; esd[2] = "CANL"; esd[3] = "GND"

    # split termination, enabled by a solder jumper (one end of the bus only)
    jp = sh.part("Jumper:SolderJumper_2_Open", "TERM", (182.88, 83.82), rot=0, fp=FP["JP_OPEN"], ref="JP")
    jp.in_bom = False  # copper only
    jp[1] = "CANH"; jp[2] = "TERM_H"
    r1 = k.R("60.4", (200.66, 93.98))
    r1[1] = "TERM_H"
    a = r1.wire_to(2, "TERM_MID")
    r2 = k.R("60.4", (200.66, 111.76))
    b = r2.wire_to(1, "TERM_MID")
    r2[2] = "CANL"
    cc = k.C("4.7n", (218.44, 111.76))
    c = cc.wire_to(1, "TERM_MID")
    cc[2] = "GND"
    ym = 102.87
    sh.wire(a, (200.66, ym)); sh.wire((200.66, ym), b); sh.wire((200.66, ym), (218.44, ym)); sh.wire((218.44, ym), c)
    sh.junction(200.66, ym)
    sh.label("TERM_MID", 205.74, ym, 0)
    sh.note(177.8, 127.0, "120 Ω split termination (60.4 + 60.4, 4.7 nF to GND).\nClose JP only on the board at a bus end.", size=1.27)

    for i, ref_x in enumerate((271.78, 309.88)):
        j = sh.part("Connector_Generic_MountingPin:Conn_01x04_MountingPin", "GH-4 CAN", (ref_x, 101.6), rot=0,
                    fp=FP["GH4"], lcsc=PART["SM04B-GHS-TB"], mpn="SM04B-GHS-TB(LF)(SN)", ref="J")
        j[1] = NC      # pin 1 carries 5 V on Pixhawk/DroneCAN cables: deliberately unconnected
        j[2] = "CANH"; j[3] = "CANL"; j[4] = "GND"; j["MP"] = "GND"
        j.stub = 5.08
    sh.note(256.54, 129.54, "GH-4 pinout: 1 NC, 2 CAN_H, 3 CAN_L, 4 GND\n(DroneCAN cable-compatible; pin 1 never\npowered from this board). J601 = in, J602 = out.", size=1.27)
    return sh


def aux(sch):
    sh = sch.sheet("aux.kicad_sch", "Aux port", page=8, ref_base=700)
    k = Kit(sh)
    sh.box(30.48, 40.64, 370.84, 205.74, "Aux port — JST-GH 8: output encoder (SPI/I2C/ABZ), step/dir, RC PWM, GPIO, motor NTC")
    j = sh.part("Connector_Generic_MountingPin:Conn_01x08_MountingPin", "GH-8 AUX", (322.58, 109.22), fp=FP["GH8H"],
                lcsc=PART["SH-SM08B-GHS-TB"], mpn="SH-SM08B-GHS-TB(LF)(SN)", ref="J")
    j[1] = "AUX_3V3"
    for n in range(1, 6):
        j[n + 1] = f"AUX{n}_EXT"
    j[7] = "AUX_ANA_EXT"; j[8] = "GND"; j["MP"] = "GND"
    j.stub = 5.08

    # 3.3 V out through a 50 mA PTC so a shorted aux cable can't pull the MCU rail (or the 5 V buck) down
    f = sh.part("Device:Polyfuse", "50mA", (264.16, 66.04), fp=FP["F0603"], lcsc=PART["0603L005/24AR"],
                mpn="0603L005/24AR", ref="F")
    f[1] = "+3V3"; f[2] = "AUX_3V3"

    # series resistors (MCU side ← → connector side)
    for n in range(1, 6):
        r = k.R("100", (142.24, 76.2 + (n - 1) * 15.24), rot=90)
        r[1] = f"AUX{n}"; r[2] = f"AUX{n}_EXT"
        r.stub = 5.08
    ra = k.R("1k", (142.24, 152.4), rot=90)
    ra[1] = "AUX_ANA"; ra[2] = "AUX_ANA_EXT"
    ra.stub = 5.08
    vert(k.C("100n", (114.3, 165.1)), "AUX_ANA", "GND")
    # motor-NTC pull-up on the connector side so the divider ratio is exact; cut JP for plain analog input
    jp = sh.part("Jumper:SolderJumper_2_Bridged", "NTC", (185.42, 139.7), rot=0, fp=FP["JP_BRIDGED"], ref="JP")
    jp.in_bom = False  # copper only
    jp[1] = "+3.3VA"; jp[2] = "AUX_NTC_PU"
    vert(k.R("10k", (205.74, 152.4)), "AUX_NTC_PU", "AUX_ANA_EXT")
    # I2C pull-ups for an AS5600-style output encoder (AUX1 = SCL, AUX5 = SDA) — fit if the module lacks them
    vert(k.R("4.7k", (226.06, 152.4), dnp=True), "AUX_3V3", "AUX1_EXT")
    vert(k.R("4.7k", (241.3, 152.4), dnp=True), "AUX_3V3", "AUX5_EXT")

    # ESD on every connector line
    e1 = sh.part("Power_Protection:TPD4E05U06DQA", "TPD4E05U06DQAR", (198.12, 88.9), fp=FP["USON10"],
                 lcsc=PART["TPD4E05U06DQAR"], mpn="TPD4E05U06DQAR", ref="D")
    e1.connect(**{"D1+": "AUX1_EXT", "D1-": "AUX2_EXT", "D2+": "AUX3_EXT", "D2-": "AUX4_EXT"})
    e1[3] = "GND"
    # flow-through package: pins 10/9/7/6 (internally unconnected) sit opposite 1/2/4/5, and TI routes each
    # line straight through its pair, so the pair shares the net (the router can enter from either side)
    e1.connect(**{"10": "AUX1_EXT", "9": "AUX2_EXT", "7": "AUX3_EXT", "6": "AUX4_EXT"})
    e1.stub = 5.08
    e2 = sh.part("Power_Protection:TPD4E05U06DQA", "TPD4E05U06DQAR", (198.12, 182.88), fp=FP["USON10"],
                 lcsc=PART["TPD4E05U06DQAR"], mpn="TPD4E05U06DQAR", ref="D")
    e2.connect(**{"D1+": "AUX5_EXT", "D1-": "AUX_ANA_EXT", "D2+": "AUX_3V3"})
    e2["D2-"] = NC
    e2[3] = "GND"
    e2.connect(**{"10": "AUX5_EXT", "9": "AUX_ANA_EXT", "7": "AUX_3V3"})       # flow-through pairs
    e2["6"] = NC
    e2.stub = 5.08

    sh.note(35.56, 50.8,
            "GH-8 pinout and modes\n"
            "1  3V3 out (PTC 50 mA)\n"
            "2  AUX1  PA15  SPI3_NSS · I2C1_SCL · TIM2_CH1 (A / STEP) · USART2_RX\n"
            "3  AUX2  PB3   SPI3_SCK · TIM2_CH2 (B / DIR) · USART2_TX\n"
            "4  AUX3  PB4   SPI3_MISO · TIM3_CH1 (RC PWM in) · ENABLE\n"
            "5  AUX4  PB5   SPI3_MOSI · TIM3_CH2\n"
            "6  AUX5  PB7   I2C1_SDA · Z index (EXTI)\n"
            "7  ANA   PA2   motor NTC (10k pull-up via JP701) or 0–3.3 V analog\n"
            "8  GND",
            size=1.27)
    return sh
