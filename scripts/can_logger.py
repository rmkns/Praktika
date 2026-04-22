#!/usr/bin/env python3
"""
CAN magistrales srauto registravimo irankis.
Uzdavinys 2-3: duomenu surinkimas ir registravimas.

Naudojimas:
    python can_logger.py                          # standartinis (can0, 500k)
    python can_logger.py --channel can0 --bitrate 250000
    python can_logger.py --duration 60            # registruoti 60 sekundziu
"""

import argparse
import csv
import time
import os
import sys
from datetime import datetime

try:
    import can
except ImportError:
    print("Klaida: reikia python-can bibliotekos")
    print("Idiegti: pip install python-can")
    sys.exit(1)


def create_output_path():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("data/logs", exist_ok=True)
    return f"data/logs/can_log_{timestamp}.csv"


def log_can_traffic(channel, bitrate, duration, output_file):
    """Registruoti CAN srauta i CSV faila."""

    try:
        bus = can.interface.Bus(channel=channel, interface="socketcan", bitrate=bitrate)
    except Exception as e:
        print(f"Klaida jungiantis prie {channel}: {e}")
        print("Patikrinkite ar CAN sasaja sukonfiguruota (sudo ./config/setup_can.sh)")
        sys.exit(1)

    print(f"CAN srauto registravimas: {channel} @ {bitrate} bps")
    print(f"Isvesties failas: {output_file}")
    if duration:
        print(f"Trukme: {duration} s")
    print("Sustabdyti: Ctrl+C")
    print()

    start_time = time.time()
    frame_count = 0

    with open(output_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp_s", "can_id_hex", "dlc", "data_hex", "is_extended", "is_remote"])

        try:
            while True:
                if duration and (time.time() - start_time) >= duration:
                    break

                msg = bus.recv(timeout=1.0)
                if msg is None:
                    continue

                elapsed = msg.timestamp - start_time if start_time else msg.timestamp
                can_id = f"{msg.arbitration_id:08X}" if msg.is_extended_id else f"{msg.arbitration_id:03X}"
                data_hex = " ".join(f"{b:02X}" for b in msg.data)

                writer.writerow([
                    f"{elapsed:.6f}",
                    can_id,
                    msg.dlc,
                    data_hex,
                    int(msg.is_extended_id),
                    int(msg.is_remote_frame),
                ])

                frame_count += 1

                if frame_count % 100 == 0:
                    elapsed_s = time.time() - start_time
                    rate = frame_count / elapsed_s if elapsed_s > 0 else 0
                    print(f"\r  Kadrai: {frame_count}  |  Laikas: {elapsed_s:.1f}s  |  Greitis: {rate:.0f} fr/s", end="")

        except KeyboardInterrupt:
            pass

    elapsed_total = time.time() - start_time
    print(f"\n\nRegistravimas baigtas.")
    print(f"  Kadru: {frame_count}")
    print(f"  Trukme: {elapsed_total:.1f} s")
    print(f"  Failas: {output_file}")

    bus.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CAN srauto registratorius")
    parser.add_argument("--channel", default="can0", help="CAN sasajos pavadinimas (default: can0)")
    parser.add_argument("--bitrate", type=int, default=500000, help="CAN bitrate (default: 500000)")
    parser.add_argument("--duration", type=int, default=None, help="Registravimo trukme sekundemis")
    parser.add_argument("--output", default=None, help="Isvesties failas (default: auto)")

    args = parser.parse_args()
    output = args.output or create_output_path()

    log_can_traffic(args.channel, args.bitrate, args.duration, output)
