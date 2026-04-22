#!/usr/bin/env python3
"""
CAN srauto emuliatorius testavimui.
Uzdavinys 9: eksperimentiniai bandymai su emuliuotais duomenimis.

Generuoja CSV faila su tipiniais CAN kadrais (periodinis srautas + diagnostiniai pranesimai).

Naudojimas:
    python can_emulator.py                          # generuoti i data/samples/
    python can_emulator.py --frames 5000 --output test.csv
"""

import argparse
import csv
import os
import random


def generate_periodic_frames(duration_s=10.0):
    """Generuoti periodinius CAN kadrus (imituoja normalu magistrales srauta)."""
    frames = []

    # Tipiniai periodiniai pranesimai (J1939/kaliu magistrale)
    periodic_messages = [
        # (CAN ID, DLC, period_ms, duomenu generatorius)
        (0x18FEF100, 8, 100, lambda: [random.randint(0, 255) for _ in range(8)]),   # EEC1 - variklio apsukas
        (0x18FEDF00, 8, 100, lambda: [random.randint(0, 255) for _ in range(8)]),   # EEC2
        (0x18FEF600, 8, 250, lambda: [random.randint(0, 255) for _ in range(8)]),   # CCVS - greitis
        (0x18FEE900, 8, 1000, lambda: [random.randint(0, 255) for _ in range(8)]),  # VIN
        (0x18FECA00, 8, 1000, lambda: [random.randint(0, 255) for _ in range(8)]),  # DM1 - aktyvios klaidos
        (0x0CF00400, 8, 50, lambda: [random.randint(0, 255) for _ in range(8)]),    # EEC1 (broadcast)
    ]

    for msg_id, dlc, period_ms, gen_data in periodic_messages:
        t = random.uniform(0, period_ms / 1000.0)  # pradinis offset
        while t < duration_s:
            jitter = random.gauss(0, period_ms * 0.01 / 1000.0)  # 1% jitter
            frames.append({
                "timestamp": t + jitter,
                "can_id": f"{msg_id:08X}",
                "dlc": dlc,
                "data": " ".join(f"{b:02X}" for b in gen_data()),
                "is_extended": 1,
                "is_remote": 0,
            })
            t += period_ms / 1000.0

    return frames


def generate_diagnostic_session(start_time):
    """Generuoti diagnostine sesija (UDS uzklausos/atsakymai)."""
    frames = []
    t = start_time

    def req(ecu_addr, data, dt=0.005):
        nonlocal t
        t += dt
        can_id = 0x18DA00F9 | (ecu_addr << 8)
        frames.append({
            "timestamp": t,
            "can_id": f"{can_id:08X}",
            "dlc": len(data) + 1,
            "data": f"{len(data):02X} " + " ".join(f"{b:02X}" for b in data),
            "is_extended": 1,
            "is_remote": 0,
        })

    def resp(ecu_addr, data, dt=0.030):
        nonlocal t
        t += dt
        can_id = 0x18DAF900 | ecu_addr
        frames.append({
            "timestamp": t,
            "can_id": f"{can_id:08X}",
            "dlc": len(data) + 1,
            "data": f"{len(data):02X} " + " ".join(f"{b:02X}" for b in data),
            "is_extended": 1,
            "is_remote": 0,
        })

    ecu = 0x2A  # AEBS

    # DiagnosticSessionControl (default)
    req(ecu, [0x10, 0x01])
    resp(ecu, [0x50, 0x01, 0x00, 0x32, 0x01, 0xF4])

    # ReadDTCInformation - count
    req(ecu, [0x19, 0x01, 0x08])
    resp(ecu, [0x59, 0x01, 0x3B, 0x01, 0x00, 0x03])

    # ReadDTCInformation - by status mask
    req(ecu, [0x19, 0x02, 0x08])
    resp(ecu, [0x59, 0x02, 0x3B,
               0x88, 0x03, 0x13, 0x28,   # SPN 904-19
               0x89, 0x03, 0x13, 0x28,   # SPN 905-19
               0x6D, 0xE0, 0xF3, 0x28])  # SPN 516205-19

    # ReadDataByIdentifier - VIN
    req(ecu, [0x22, 0xF1, 0x90])
    resp(ecu, [0x62, 0xF1, 0x90] + list(b"XLRASF5300G414600"))

    return frames


def main():
    parser = argparse.ArgumentParser(description="CAN srauto emuliatorius")
    parser.add_argument("--duration", type=float, default=10.0, help="Trukme sekundemis (default: 10)")
    parser.add_argument("--output", default=None, help="Isvesties failas")
    args = parser.parse_args()

    output = args.output
    if not output:
        os.makedirs("data/samples", exist_ok=True)
        output = "data/samples/emulated_can.csv"

    print(f"Generuojamas CAN srautas ({args.duration}s)...")

    frames = generate_periodic_frames(args.duration)
    frames.extend(generate_diagnostic_session(args.duration * 0.3))
    frames.extend(generate_diagnostic_session(args.duration * 0.6))
    frames.sort(key=lambda f: f["timestamp"])

    with open(output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp_s", "can_id_hex", "dlc", "data_hex", "is_extended", "is_remote"])
        for frame in frames:
            writer.writerow([
                f"{frame['timestamp']:.6f}",
                frame["can_id"],
                frame["dlc"],
                frame["data"],
                frame["is_extended"],
                frame["is_remote"],
            ])

    print(f"Sugeneruota: {len(frames)} kadru -> {output}")
    print(f"\nAnalizuoti: python scripts/can_analyzer.py {output}")
    print(f"Diagnostika: python scripts/diag_interpreter.py {output}")


if __name__ == "__main__":
    main()
