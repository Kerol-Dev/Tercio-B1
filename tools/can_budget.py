#!/usr/bin/env python3
"""CAN-FD bus-time budget for Tercio protocol v2 traffic.

Estimates the on-wire time of one CAN-FD frame (11-bit ID, BRS on) and how
many nodes fit a given exchange rate. Stuff bits are modelled as 1 per 5 bits
in the dynamic-stuffing fields (worst-case-ish, real traffic is lower) plus the
fixed stuff bits of the FD CRC field, so the results are slightly pessimistic.

    python3 tools/can_budget.py               # the tables in docs/07-firmware.md
    python3 tools/can_budget.py 1000000 5000000
"""
import sys

FD_SIZES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64]


def fd_len(n):
    return next(s for s in FD_SIZES if s >= n)


def frame_us(payload, nominal=500_000, data=2_500_000):
    n = fd_len(payload)
    # Nominal-rate part: SOF, 11-bit ID, RRS, IDE, FDF, res, BRS  (17 bits, stuffed)
    #                    + CRC delimiter, ACK, ACK delimiter, EOF(7), IFS(3) (13 bits, not stuffed)
    nominal_bits = 17 * 1.2 + 13
    # Data-rate part: ESI, DLC(4), data, stuff count(4), CRC(17 or 21) with fixed stuff bits
    crc = 17 if n <= 16 else 21
    data_bits = (1 + 4 + 8 * n) * 1.2 + 4 + crc + (crc + 4) // 4
    return nominal_bits / nominal * 1e6 + data_bits / data * 1e6


def main():
    nominal = int(sys.argv[1]) if len(sys.argv) > 1 else 500_000
    data = int(sys.argv[2]) if len(sys.argv) > 2 else 2_500_000
    print(f"Bus {nominal / 1e3:.0f}k / {data / 1e6:.1f}M\n")
    print("| Payload (bytes) | Padded | Frame time (µs) |")
    print("|---:|---:|---:|")
    for p in (2, 13, 22, 26, 38, 64):
        print(f"| {p} | {fd_len(p)} | {frame_us(p, nominal, data):.0f} |")

    # Exchanges per node per cycle.
    cases = {
        "Telemetry only (38 B, today's S1 frame)": [38],
        "Command (MoveTo 22 B) + telemetry (38 B)": [22, 38],
        "Impedance command (26 B) + compact reply (22 B)": [26, 22],
    }
    print("\n| Traffic per node per cycle | Bus time per node (µs) | Nodes at 1 kHz | at 500 Hz | at 250 Hz |")
    print("|---|---:|---:|---:|---:|")
    for name, frames in cases.items():
        t = sum(frame_us(p, nominal, data) for p in frames)
        fit = lambda hz: int(0.7 * 1e6 / hz // t)  # keep bus load at or below 70 %
        print(f"| {name} | {t:.0f} | {fit(1000)} | {fit(500)} | {fit(250)} |")
    print("\nNode counts keep the bus at or below 70 % load.")


if __name__ == "__main__":
    main()
