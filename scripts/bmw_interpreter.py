#!/usr/bin/env python3
"""
BMW F30 330e ISTA diagnostiniu pranesimu interpretatorius.
Nuskaito CAN loga ir interpretuoja ISTA <-> ECU komunikacija.

Naudojimas:
    python bmw_interpreter.py data/logs/bmw_f30_*.csv
    python bmw_interpreter.py data/logs/bmw_f30_*.csv --ecu DME
    python bmw_interpreter.py data/logs/bmw_f30_*.csv --dtc-only
"""

import argparse
import csv
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))
from bmw_f30 import *
from iso_tp import IsoTpReassembler
from uds import UDS_SERVICES, NRC_NAMES, DTC_SUBFUNCTIONS, decode_session


def load_log(filepath):
    """Nuskaityti CAN loga."""
    frames = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            frames.append({
                "timestamp": float(row["timestamp_s"]),
                "can_id": int(row["can_id_hex"], 16),
                "dlc": int(row["dlc"]),
                "data": bytes.fromhex(row["data_hex"].replace(" ", "")) if row["data_hex"].strip() else b"",
            })
    return frames


# ISO-TP reassembly dabar atliekama per IsoTpReassembler is config/iso_tp.py
# Senas extract_uds_payload pasalintas — jis nepalaike multi-frame surinkimo


def interpret_frame(can_id, payload, ecu_filter=None):
    """Interpretuoti viena UDS kadra. Grazina (ecu_name, direction, text) arba None."""

    ecu_name = get_ecu_name(can_id)
    if ecu_name is None:
        return None

    if ecu_filter and ecu_name != ecu_filter and ecu_name != TESTER_NAME:
        return None

    if can_id == TESTER_ID:
        direction = "REQ"
        return _interpret_request(payload, direction)
    else:
        direction = "RESP"
        return _interpret_response(payload, direction, ecu_name)


def _interpret_request(payload, direction):
    """Interpretuoti ISTA uzklause."""
    if not payload:
        return None

    sid = payload[0]
    data = payload[1:]
    name = UDS_SERVICES.get(sid, f"Service_0x{sid:02X}")
    details = []

    if sid == 0x10 and len(data) >= 1:
        details.append(f"session={decode_session(data[0])}")

    elif sid == 0x19 and len(data) >= 1:
        details.append(DTC_SUBFUNCTIONS.get(data[0], f"sub=0x{data[0]:02X}"))
        if data[0] in (0x01, 0x02) and len(data) >= 2:
            details.append(f"statusMask=0x{data[1]:02X}")
        elif data[0] in (0x04, 0x06) and len(data) >= 4:
            dtc = (data[1] << 16) | (data[2] << 8) | data[3]
            details.append(f"DTC=0x{dtc:06X}")

    elif sid == 0x22 and len(data) >= 2:
        did = (data[0] << 8) | data[1]
        did_name = get_did_name(did)
        details.append(f"DID=0x{did:04X}")
        if did_name:
            details.append(did_name)

    elif sid == 0x27 and len(data) >= 1:
        level = data[0]
        details.append("requestSeed" if level % 2 == 1 else "sendKey")
        details.append(f"level={level}")

    elif sid == 0x31 and len(data) >= 3:
        sub = {0x01: "start", 0x02: "stop", 0x03: "result"}
        routine_id = (data[1] << 8) | data[2]
        details.append(f"{sub.get(data[0], f'0x{data[0]:02X}')}")
        details.append(f"routine=0x{routine_id:04X}")

    elif sid == 0x14 and len(data) >= 3:
        group = (data[0] << 16) | (data[1] << 8) | data[2]
        details.append(f"group=0x{group:06X}")

    elif sid == 0x3E:
        details.append("keepAlive")

    detail_str = ", ".join(details) if details else ""
    return direction, TESTER_NAME, f"{name} ({detail_str})" if detail_str else name


def _interpret_response(payload, direction, ecu_name):
    """Interpretuoti ECU atsakyma."""
    if not payload:
        return None

    sid = payload[0]
    data = payload[1:]

    # Neigiamas atsakymas
    if sid == 0x7F and len(data) >= 2:
        failed_sid = data[0]
        nrc = data[1]
        sid_name = UDS_SERVICES.get(failed_sid, f"0x{failed_sid:02X}")
        nrc_name = NRC_NAMES.get(nrc, f"0x{nrc:02X}")
        return direction, ecu_name, f"NEGATIVE {sid_name} -> {nrc_name}"

    # Teigiamas atsakymas
    req_sid = sid - 0x40
    name = UDS_SERVICES.get(req_sid, f"Service_0x{req_sid:02X}")
    details = []

    if req_sid == 0x10 and len(data) >= 1:
        details.append(f"session={decode_session(data[0])}")

    elif req_sid == 0x19 and len(data) >= 1:
        subfunc = data[0]
        if subfunc == 0x01 and len(data) >= 4:
            count = (data[2] << 8) | data[3]
            details.append(f"DTCCount={count}")
        elif subfunc == 0x02:
            dtc_bytes = data[1:]  # po availabilityMask
            dtc_count = len(dtc_bytes) // 4
            details.append(f"{dtc_count} DTCs")
            # Israsyti pirmus kelis DTC
            for i in range(min(dtc_count, 5)):
                offset = 1 + i * 4
                if offset + 3 < len(data):
                    d0, d1, d2 = data[offset], data[offset+1], data[offset+2]
                    status = data[offset+3]
                    dtc_hex = f"{d0:02X}{d1:02X}{d2:02X}"
                    status_flags = decode_dtc_status(status)
                    flag_str = "|".join(status_flags[:2]) if status_flags else f"0x{status:02X}"
                    details.append(f"DTC {dtc_hex} [{flag_str}]")

    elif req_sid == 0x22 and len(data) >= 2:
        did = (data[0] << 8) | data[1]
        did_name = get_did_name(did)
        value = data[2:]
        # Bandyti ASCII
        try:
            text = bytes(value).decode("ascii", errors="replace").rstrip("\x00 ")
            if text and all(c.isprintable() for c in text):
                details.append(f"DID=0x{did:04X} = \"{text}\"")
            else:
                details.append(f"DID=0x{did:04X} = [{' '.join(f'{b:02X}' for b in value[:8])}]")
        except:
            details.append(f"DID=0x{did:04X}")
        if did_name:
            details.append(did_name)

    detail_str = ", ".join(details) if details else ""
    return direction, ecu_name, f"+{name} ({detail_str})" if detail_str else f"+{name}"


def process_log(filepath, ecu_filter=None, dtc_only=False):
    """Apdoroti visa loga su pilnu ISO-TP multi-frame surinkimu."""
    frames = load_log(filepath)
    print(f"Nuskaityta kadru: {len(frames)}\n")

    if dtc_only:
        print("=== KLAIDU (DTC) SKAITYMAS ===\n")

    reassembler = IsoTpReassembler()
    sf_count = 0
    multiframe_count = 0

    for f in frames:
        can_id = f["can_id"]
        kind, payload = reassembler.feed(can_id, f["data"])

        if kind in ("partial", "ignored", "error") or payload is None:
            continue

        if kind == "single":
            sf_count += 1
        elif kind == "complete":
            multiframe_count += 1

        result = interpret_frame(can_id, payload, ecu_filter)
        if result is None:
            continue

        direction, ecu_name, text = result

        if dtc_only and "DTC" not in text and "ReadDTCInformation" not in text and "ClearDiagnostic" not in text:
            continue

        ts = f"{f['timestamp']:10.3f}"
        arrow = ">>" if direction == "REQ" else "<<"
        data_hex = " ".join(f"{b:02X}" for b in payload[:32])
        if len(payload) > 32:
            data_hex += f" ... (+{len(payload) - 32} baitu)"
        mf_tag = " [MF]" if kind == "complete" else ""

        print(f"[{ts}] {arrow} {ecu_name:<8}{mf_tag} {text}")
        print(f"             {data_hex}")

    print(f"\nApdorota: {sf_count} SF + {multiframe_count} multi-frame zinuciu")


def main():
    parser = argparse.ArgumentParser(description="BMW F30 ISTA diagnostikos interpretatorius")
    parser.add_argument("logfile", help="CAN log CSV failas")
    parser.add_argument("--ecu", default=None, help="Filtruoti pagal ECU (pvz: DME, KOMBI, SME)")
    parser.add_argument("--dtc-only", action="store_true", help="Rodyti tik DTC susijusius pranesimu")
    args = parser.parse_args()

    process_log(args.logfile, args.ecu, args.dtc_only)


if __name__ == "__main__":
    main()
