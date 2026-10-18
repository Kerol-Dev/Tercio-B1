"""Symbols KiCad's library does not have, built from the vendor pin tables.

DRV8353RS: TI SLVSDY6A (June 2019), "Pin Functions—48-Pin DRV8353R Devices",
RGZ package, SPI variant (DRV8353RS column).
MT6835: MagnTek MT6835 datasheet v1.3 (Dec 2022), pin list, TSSOP-16.
"""
from __future__ import annotations

from .catalog import FP
from .symbols import Library, make_ic

LIB = "Tercio_B1"


def drv8353rs():
    # (pin, name, type); None = blank row
    top = [("5", "VM", "power_in"), None, ("6", "VDRAIN", "input"), None, ("43", "VIN", "power_in"), None,
           None, ("26", "VREF", "power_in")]
    left = [
        ("4", "CPH", "passive"),
        ("3", "CPL", "passive"),
        ("7", "VCP", "power_out"),
        ("2", "VGLS", "power_out"),
        ("40", "DVDD", "power_out"),
        None,
        ("45", "BST", "passive"),
        ("42", "SW", "output"),
        ("44", "VCC", "power_out"),
        ("48", "FB", "input"),
        ("47", "RT/SD", "input"),
        ("46", "RCL", "input"),
        None,
        ("33", "ENABLE", "input"),
        ("32", "~{SCS}", "input"),
        ("31", "SCLK", "input"),
        ("30", "SDI", "input"),
        ("29", "SDO", "open_collector"),
        ("28", "~{FAULT}", "open_collector"),
        None,
        ("34", "INHA", "input"),
        ("35", "INLA", "input"),
        ("36", "INHB", "input"),
        ("37", "INLB", "input"),
        ("38", "INHC", "input"),
        ("39", "INLC", "input"),
    ]
    right = [
        ("8", "GHA", "output"),
        ("9", "SHA", "input"),
        ("10", "GLA", "output"),
        ("11", "SPA", "input"),
        ("12", "SNA", "input"),
        None,
        ("17", "GHB", "output"),
        ("16", "SHB", "input"),
        ("15", "GLB", "output"),
        ("14", "SPB", "input"),
        ("13", "SNB", "input"),
        None,
        ("18", "GHC", "output"),
        ("19", "SHC", "input"),
        ("20", "GLC", "output"),
        ("21", "SPC", "input"),
        ("22", "SNC", "input"),
        None,
        None,
        ("25", "SOA", "output"),
        ("24", "SOB", "output"),
        ("23", "SOC", "output"),
    ]
    bottom = [("1", "GND", "power_in"), ("27", "AGND", "power_in"), ("41", "DGND", "power_in"),
              ("49", "PAD", "power_in")]
    return make_ic("DRV8353RS", "U", FP["RGZ48"], "https://www.ti.com/lit/ds/symlink/drv8353.pdf",
                   "100 V three-phase smart gate driver, 3 current-sense amplifiers, SPI, LM5008A buck",
                   left, right, top=top, bottom=bottom, width=25.4)


def mt6835():
    left = [
        ("8", "CSN", "input"),
        ("7", "SCK", "input"),
        ("6", "MOSI", "input"),
        ("5", "MISO", "tri_state"),
        None,
        ("4", "CAL_EN", "input"),
        ("13", "TEST_EN", "input"),
        ("11", "TEST", "input"),
    ]
    right = [
        ("16", "A", "output"),
        ("15", "B", "output"),
        ("14", "Z", "output"),
        None,
        ("1", "U", "output"),
        ("2", "V", "output"),
        ("3", "W", "output"),
        ("10", "OUT", "output"),
    ]
    return make_ic("MT6835", "U", FP["TSSOP16"], "https://www.magntek.com.cn/",
                   "21-bit magnetic angle encoder, SPI/ABZ/UVW/PWM, 3.3-5 V",
                   left, right, top=[("9", "VDD", "power_in")], bottom=[("12", "VSS", "power_in")], width=17.78)


def register(lib: Library):
    lib.add_custom(f"{LIB}:DRV8353RS", drv8353rs())
    lib.add_custom(f"{LIB}:MT6835", mt6835())
