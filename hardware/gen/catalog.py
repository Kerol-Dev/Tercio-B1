"""Part catalogue: footprints, LCSC codes and small placement helpers.

LCSC codes were checked against the live JLCPCB catalogue on 2026-10-12
(tools/verify_bom.py re-checks them). "B" = JLC Basic part.
"""
from __future__ import annotations

from .model import Sheet

# ---- footprints ---------------------------------------------------------------------
FP = {
    "R0402": "Resistor_SMD:R_0402_1005Metric",
    "R0603": "Resistor_SMD:R_0603_1608Metric",
    "R0805": "Resistor_SMD:R_0805_2012Metric",
    "C0402": "Capacitor_SMD:C_0402_1005Metric",
    "C0603": "Capacitor_SMD:C_0603_1608Metric",
    "C0805": "Capacitor_SMD:C_0805_2012Metric",
    "C1210": "Capacitor_SMD:C_1210_3225Metric",
    "CP10x10": "Capacitor_SMD:CP_Elec_10x10",
    "CP6.3x7.7": "Capacitor_SMD:CP_Elec_6.3x7.7",
    "LED0603": "LED_SMD:LED_0603_1608Metric",
    "LED0805": "LED_SMD:LED_0805_2012Metric",
    "FB0603": "Inductor_SMD:L_0603_1608Metric",
    "L5040": "Inductor_SMD:L_Sunlord_SWPA5040S",
    "L6045": "Inductor_SMD:L_Sunlord_SWPA6045S",
    "SMA": "Diode_SMD:D_SMA",
    "SMB": "Diode_SMD:D_SMB",
    "SMC": "Diode_SMD:D_SMC",
    "SOD323": "Diode_SMD:D_SOD-323",
    "SOD123F": "Diode_SMD:D_SOD-123F",
    "F0805": "Fuse:Fuse_0805_2012Metric",
    "F0603": "Fuse:Fuse_0603_1608Metric",
    "XTAL3225": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
    "TDSON8": "Package_TO_SOT_SMD:TDSON-8-1",
    "SHUNT2512K": "Tercio_B1:R_2512_Kelvin",  # 2-terminal 2512 with Kelvin sense pads (generated at layout)
    "MOTORPAD": "Tercio_B1:MotorPad_3.6x6mm",  # generated at layout
    "XT30PW": "Connector_AMASS:AMASS_XT30PW-M_1x02_P2.50mm_Horizontal",
    "GH4": "Connector_JST:JST_GH_SM04B-GHS-TB_1x04-1MP_P1.25mm_Horizontal",   # right angle, cable entry at the board edge
    "GH8H": "Connector_JST:JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal",
    "GH8V": "Connector_JST:JST_GH_BM08B-GHS-TBT_1x08-1MP_P1.25mm_Vertical",
    "TC2030": "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical",
    "SWDPADS": "Tercio_B1:SWD_Pads_1x05_P2.54mm",  # generated
    "JP_OPEN": "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
    "JP_BRIDGED": "Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm",
    "TP": "Tercio_B1:TestPad_D0.9mm",  # generated: 0.9 mm pad, 1.2 mm courtyard
    "HOLE_M25": "MountingHole:MountingHole_2.7mm_M2.5",
    "RGZ48": "Package_DFN_QFN:Texas_RGZ0048A_VQFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm_ThermalVias",
    "TSSOP16": "Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
    "LQFP48": "Package_QFP:LQFP-48_7x7mm_P0.5mm",
    "SOIC8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "SOT23": "Package_TO_SOT_SMD:SOT-23",
    "SOT23_5": "Package_TO_SOT_SMD:SOT-23-5",
    "USON10": "Package_SON:USON-10_2.5x1.0mm_P0.5mm",
}

# (value, package) -> LCSC. Values are written the way they print on the schematic.
RES = {
    ("0", "0402"): "C17168",       # B
    ("1", "0805"): "C25271",       # B
    ("10", "0402"): "C25077",      # B
    ("10", "0603"): "C22859",      # B
    ("22", "0402"): "C25092",      # B
    ("47", "0603"): "C23182",      # B
    ("60.4", "0402"): "C137954",   # Extended (CAN split termination)
    ("100", "0402"): "C25076",     # B
    ("1k", "0402"): "C11702",      # B
    ("1.5k", "0402"): "C25867",    # B
    ("2.2k", "0402"): "C25879",    # B
    ("4.7k", "0402"): "C25900",    # B
    ("5.1k", "0402"): "C25905",    # B
    ("10k", "0402"): "C25744",     # B
    ("100k", "0402"): "C25741",    # B
    ("100k", "0603"): "C25803",    # B
    ("150k", "0603"): "C22807",    # B
    ("200k", "0603"): "C25811",    # B
}

CAP = {
    ("12p", "0402"): ("C1547", "50V C0G"),       # B
    ("1n", "0402"): ("C1523", "50V"),            # B
    ("4.7n", "0402"): ("C1538", "50V"),          # B
    ("10n", "0402"): ("C15195", "50V"),          # B
    ("100n", "0402"): ("C1525", "16V"),          # B
    ("1u", "0402"): ("C52923", "25V"),           # B
    ("470n", "0603"): ("C1623", "25V"),          # B
    ("1u", "0603"): ("C15849", "50V"),           # B
    ("4.7u", "0603"): ("C19666", "16V"),         # B
    ("10u", "0603"): ("C19702", "10V"),          # B
    ("22u", "0805"): ("C45783", "25V"),          # B
    ("47n", "0603"): ("C576852", "100V"),        # Extended
    ("100n", "0805"): ("C28233", "100V"),        # B
    ("100n", "0603"): ("C15725", "100V"),        # Samsung CL10B104KC8NNNC (VM bypass: fits the DRV's left band)
    ("1u", "0805"): ("C5370002", "100V"),        # Extended
    ("4.7u", "1210"): ("C381466", "100V"),       # Extended
    ("10u", "1210"): ("C5156756", "100V"),       # Extended, X7R
}

PART = {
    "STM32G431CBT6": "C529355",
    "DRV8353RSRGZR": "C506246",
    "MT6835GT-STD-R": "C2932578",
    "MCP2562FDT-E/SN": "C511335",
    "TLV75533PDBVR": "C404027",
    "BSC030N08NS5": "C501507",
    "RLP25FEGR001": "C459678",
    "SMBJ54A": "C2891330",
    "SMCJ54A": "C438116",
    "VZH470M1KTR-1010": "C249920",
    "JVJ100V22M6x8": "C46550391",  # 22 µF 100 V, 6.3 x 7.7 mm
    "X322516MLB4SI": "C13738",     # B
    "NCP18XH103F03RB": "C13564",
    "NUP2105LT1G": "C14486",
    "TPD4E05U06DQAR": "C138714",
    "XT30PW-M": "C431092",
    "SM04B-GHS-TB": "C189895",
    "BM04B-GHS-TBT": "C161692",
    "BM08B-GHS-TBT": "C133062",
    "SH-SM08B-GHS-TB": "C42376901",  # Shou Han GH-compatible right angle 8P; genuine JST SM08B had 0 JLC stock (2026-10-12)
    "SWPA5040S101MT": "C88132",
    "SWPA6045S101MT": "C60633",    # 100 µH, 1 A saturation
    "SS210": "C14996",             # B
    "MBR1H100SFT3G": "C235757",    # onsemi 100 V 1 A Schottky, SOD-123FL (a quarter of the SMA's area)
    "GZ1608D601TF": "C1002",       # B ferrite 600R@100MHz
    "PESD5V0S1BA": "C2827694",
    "0805L010/24XR": "C7472554",   # PTC 100 mA hold
    "0603L005/24AR": "C7472511",   # PTC 50 mA hold
    "KT-0805G": "C2297",           # B green
    "KT-0603R": "C2286",           # B red
}


class Kit:
    """Placement helpers bound to one sheet."""

    def __init__(self, sheet: Sheet):
        self.sh = sheet

    def R(self, value, at, rot=0, pkg="0402", dnp=False, **kw):
        lcsc = "" if dnp else RES[(value, pkg)]
        shown = value if value != "0" else "0R"
        return self.sh.part("Device:R", shown, at, rot, fp=FP["R" + pkg], lcsc=lcsc, dnp=dnp, **kw)

    def C(self, value, at, rot=0, pkg="0402", dnp=False, **kw):
        lcsc, rating = ("", "") if dnp and (value, pkg) not in CAP else CAP[(value, pkg)]
        shown = f"{value}F {rating}".replace("uF", "µF").strip()
        return self.sh.part("Device:C", shown, at, rot, fp=FP["C" + pkg], lcsc="" if dnp else lcsc, dnp=dnp, **kw)

    def flag(self, net, at, rot=0):
        f = self.sh.part("power:PWR_FLAG", "PWR_FLAG", at, rot, ref="#FLG")
        f[1] = net
        return f

    def tp(self, net, at, rot=0):
        t = self.sh.part("Connector:TestPoint", net, at, rot, fp=FP["TP"], ref="TP")
        t.in_bom = False
        return t
