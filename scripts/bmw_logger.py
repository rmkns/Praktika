#!/usr/bin/env python3
"""
BMW F30 330e CAN srauto loggeris su ISTA diagnostikos filtravimu.

Registruoja viska kas eina per OBD D-CAN magistrale kol ISTA dirba.
Automatiskai atpazista diagnostinius pranesimu (ISTA <-> ECU).

Naudojimas:
    1. Prijungti Raspberry Pi per OBD-II
    2. Paleisti si skripta
    3. Paleisti ISTA diagnostika is kito kompiuterio (per ICOM arba ENET kabeliu)
    4. Skriptas registruos visa CAN srauta

    python bmw_logger.py
    python bmw_logger.py --duration 300 --output bmw_diag.csv
"""

import argparse
import csv
import time
import os
import sys

try:
    import can
except ImportError:
    print("Klaida: pip install python-can")
    sys.exit(1)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))
from bmw_f30 import *


def log_bmw_traffic(channel, duration, output_file):
    """Registruoti BMW CAN srauta su diagnostiniu pranesimu atpazinimu."""

    try:
        bus = can.interface.Bus(channel=channel, interface="socketcan", bitrate=CAN_BITRATE)
    except Exception as e:
        print(f"Klaida: {e}")
        print("Paleiskite: sudo ./config/setup_can.sh 500000")
        sys.exit(1)

    print(f"BMW F30 330e CAN loggeris")
    print(f"Kanalas: {channel} @ {CAN_BITRATE} bps")
    print(f"Failas: {output_file}")
    if duration:
        print(f"Trukme: {duration} s")
    print(f"Laukiama ISTA diagnostikos srauto...")
    print(f"Ctrl+C — sustabdyti\n")

    start_time = time.time()
    frame_count = 0
    diag_count = 0

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

                elapsed = time.time() - start_time
                can_id_str = f"{msg.arbitration_id:03X}"
                data_hex = " ".join(f"{b:02X}" for b in msg.data)

                writer.writerow([
                    f"{elapsed:.6f}",
                    can_id_str,
                    msg.dlc,
                    data_hex,
                    int(msg.is_extended_id),
                    int(msg.is_remote_frame),
                ])

                frame_count += 1

                # Atpazinti diagnostinius kadrus ir rodyti gyvai
                ecu_name = get_ecu_name(msg.arbitration_id)
                is_diag = ecu_name is not None

                if is_diag:
                    diag_count += 1
                    direction = ">>" if msg.arbitration_id == TESTER_ID else "<<"

                    # Dekoduoti UDS servisa
                    service_info = ""
                    if len(msg.data) >= 2:
                        # ISO-TP single frame
                        tp_len = msg.data[0] & 0x0F
                        if (msg.data[0] >> 4) == 0 and tp_len > 0:
                            sid = msg.data[1]
                            if msg.arbitration_id == TESTER_ID:
                                service_info = _decode_request(sid, msg.data[2:1+tp_len])
                            else:
                                service_info = _decode_response(sid, msg.data[2:1+tp_len])

                    print(f"  {direction} {ecu_name:<8} [{can_id_str}] {data_hex:<24} {service_info}")

                # Status eilute
                if frame_count % 500 == 0:
                    print(f"\r  Kadrai: {frame_count} | Diagnostiniai: {diag_count} | {elapsed:.0f}s", end="")

        except KeyboardInterrupt:
            pass

    elapsed_total = time.time() - start_time
    print(f"\n\nBaigta. Kadru: {frame_count}, Diagnostiniu: {diag_count}, Laikas: {elapsed_total:.1f}s")
    print(f"Failas: {output_file}")
    print(f"\nAnalizuoti:")
    print(f"  python scripts/can_analyzer.py {output_file} --plot")
    print(f"  python scripts/bmw_interpreter.py {output_file}")

    bus.shutdown()


def _decode_request(sid, data):
    """
    Trumpai dekoduoti UDS uzklausos servisa LIVE LOGGING konteksto.

    Cia naudojami trumpiniai pavadinimu (pvz. "ReadDTC" vs "ReadDTCInformation")
    kad live srauto eilute tilptu i terminalo plota. Detaliai analizei naudok
    bmw_interpreter.py — jis naudoja pilna uds.UDS_SERVICES zodyna.
    """
    services = {
        0x10: "DiagSession",
        0x11: "ECUReset",
        0x14: "ClearDTC",
        0x19: "ReadDTC",
        0x22: "ReadDID",
        0x27: "SecAccess",
        0x2E: "WriteDID",
        0x2F: "IOControl",
        0x31: "Routine",
        0x34: "ReqDownload",
        0x36: "TransferData",
        0x3E: "TesterPresent",
    }
    name = services.get(sid, f"SID 0x{sid:02X}")

    if sid == 0x22 and len(data) >= 2:
        did = (data[0] << 8) | data[1]
        did_name = get_did_name(did)
        return f"{name} DID=0x{did:04X}" + (f" ({did_name})" if did_name else "")
    elif sid == 0x19 and len(data) >= 1:
        subfuncs = {0x01: "count", 0x02: "byStatus", 0x04: "snapshot", 0x06: "extended"}
        return f"{name} {subfuncs.get(data[0], f'sub=0x{data[0]:02X}')}"
    elif sid == 0x10 and len(data) >= 1:
        sessions = {0x01: "default", 0x02: "programming", 0x03: "extended", 0x41: "codingSession"}
        return f"{name} {sessions.get(data[0], f'0x{data[0]:02X}')}"

    return name


def _decode_response(sid, data):
    """Trumpai dekoduoti UDS atsakyma."""
    if sid == 0x7F and len(data) >= 2:
        nrc_names = {0x11: "notSupported", 0x22: "conditionsNotCorrect",
                     0x31: "outOfRange", 0x33: "securityDenied", 0x78: "pending"}
        nrc = nrc_names.get(data[1], f"NRC=0x{data[1]:02X}")
        return f"NEGATIVE {nrc}"
    elif sid >= 0x40:
        return f"+Response 0x{sid:02X}"
    return ""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BMW F30 CAN loggeris")
    parser.add_argument("--channel", default=CAN_CHANNEL)
    parser.add_argument("--duration", type=int, default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    output = args.output
    if not output:
        os.makedirs("data/logs", exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"data/logs/bmw_f30_{ts}.csv"

    log_bmw_traffic(args.channel, args.duration, output)
