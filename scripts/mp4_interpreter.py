#!/usr/bin/env python3
"""
Mercedes-Benz Actros MP4 diagnostiniu pranesimu interpretatorius.
Nuskaito CAN loga ir interpretuoja Xentry/DAS <-> ECU komunikacija
naudojant UDS (ISO 14229) protokola per ISO-TP (ISO 15765-2).

Naudojimas:
    python mp4_interpreter.py data/logs/can_log_*.csv
    python mp4_interpreter.py data/logs/can_log_*.csv --ecu MCM
    python mp4_interpreter.py data/logs/can_log_*.csv --dtc-only
"""

import argparse
import csv
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))
from mb_actros_mp4 import *
from iso_tp import IsoTpReassembler
from uds import NRC_NAMES, DTC_SUBFUNCTIONS, decode_session


def load_log(filepath):
    """Nuskaityti CAN loga is CSV failo."""
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


def classify_frame(can_id):
    """
    Nustatyti ar kadras yra MP4 diagnostinis ir kuria kryptimi jis eina.
    Grazina (direction, ecu_addr, ecu_name, tester_addr) arba (None, None, None, None).

    MP4 naudoja 29-bit ID, su bet kuriuo testerio adresu F1-F9:
      0x18DA<ecu><tester> — testeris -> ECU (REQ)
      0x18DA<tester><ecu> — ECU -> testeris (RESP)

    Pagrindinis Xentry/DAS testeris yra F1, taciau realiame sraute galima
    pamatyti F2-F9 kai prijungti keli irankiai vienu metu.
    """
    if not (0x18DA0000 <= can_id <= 0x18DAFFFF):
        return None, None, None, None

    low = can_id & 0xFF
    mid = (can_id >> 8) & 0xFF

    if low in TESTER_ADDRS:
        ecu_addr = mid
        ecu_info = ECU_MAP.get(ecu_addr)
        ecu_name = ecu_info["name"] if ecu_info else f"ECU_0x{ecu_addr:02X}"
        return "REQ", ecu_addr, ecu_name, low

    if mid in TESTER_ADDRS:
        ecu_addr = low
        ecu_info = ECU_MAP.get(ecu_addr)
        ecu_name = ecu_info["name"] if ecu_info else f"ECU_0x{ecu_addr:02X}"
        return "RESP", ecu_addr, ecu_name, mid

    return None, None, None, None


# IsoTpReassembler is dabar gyvena bendroje bibliotekoje:
# config/iso_tp.py — kad visi skriptai naudotu ta pati implementacija


def _interpret_request(payload, ecu_name):
    """Interpretuoti testerio uzklausa."""
    if not payload:
        return None

    sid = payload[0]
    data = payload[1:]
    name = get_service_name(sid) or f"Service_0x{sid:02X}"
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
        details.append(f"DID=0x{did:04X}")
        did_name = get_did_name(did)
        if did_name:
            details.append(did_name)

    elif sid == 0x27 and len(data) >= 1:
        level = data[0]
        details.append("requestSeed" if level % 2 == 1 else "sendKey")
        details.append(f"level=0x{level:02X}")

    elif sid == 0x31 and len(data) >= 3:
        sub = {0x01: "start", 0x02: "stop", 0x03: "result"}
        routine_id = (data[1] << 8) | data[2]
        details.append(sub.get(data[0], f"0x{data[0]:02X}"))
        details.append(f"routine=0x{routine_id:04X}")

    elif sid == 0x14 and len(data) >= 3:
        # UDS Clear DTC: 3 baitai grupes (Mercedes naudoja 0xFFFFFF = "visi")
        group = (data[0] << 16) | (data[1] << 8) | data[2]
        if group == 0xFFFFFF:
            details.append("group=ALL")
        else:
            details.append(f"group=0x{group:06X}")

    elif sid == 0x3E:
        details.append("keepAlive")

    detail_str = ", ".join(details) if details else ""
    return f"{name} ({detail_str})" if detail_str else name


def _interpret_response(payload, ecu_name):
    """Interpretuoti ECU atsakyma."""
    if not payload:
        return None

    sid = payload[0]
    data = payload[1:]

    # Neigiamas atsakymas: 7F <failed_sid> <nrc>
    if sid == 0x7F and len(data) >= 2:
        failed_sid = data[0]
        nrc = data[1]
        sid_name = get_service_name(failed_sid) or f"0x{failed_sid:02X}"
        nrc_name = NRC_NAMES.get(nrc, f"0x{nrc:02X}")
        return f"NEGATIVE {sid_name} -> {nrc_name}"

    # Teigiamas atsakymas: response SID = request SID + 0x40
    req_sid = sid - 0x40
    name = get_service_name(req_sid) or f"Service_0x{req_sid:02X}"
    details = []

    if req_sid == 0x10 and len(data) >= 1:
        details.append(f"session={decode_session(data[0])}")

    elif req_sid == 0x19 and len(data) >= 1:
        subfunc = data[0]
        if subfunc == 0x01 and len(data) >= 4:
            count = (data[2] << 8) | data[3]
            details.append(f"DTCCount={count}")
        elif subfunc == 0x02:
            # po availabilityMask seka 4 baitu DTC irasai
            dtc_bytes = data[1:]
            dtc_count = len(dtc_bytes) // 4
            details.append(f"{dtc_count} DTCs")
            for i in range(min(dtc_count, 5)):
                offset = 1 + i * 4
                if offset + 3 < len(data):
                    d0, d1, d2 = data[offset], data[offset + 1], data[offset + 2]
                    status = data[offset + 3]
                    dtc_hex = f"{d0:02X}{d1:02X}{d2:02X}"
                    status_flags = decode_dtc_status(status)
                    flag_str = "|".join(status_flags[:2]) if status_flags else f"0x{status:02X}"
                    details.append(f"DTC {dtc_hex} [{flag_str}]")

    elif req_sid == 0x22 and len(data) >= 2:
        did = (data[0] << 8) | data[1]
        value = data[2:]
        try:
            text = bytes(value).decode("ascii", errors="replace").rstrip("\x00 ")
            if text and all(c.isprintable() for c in text):
                details.append(f"DID=0x{did:04X} = \"{text}\"")
            else:
                details.append(f"DID=0x{did:04X} = [{' '.join(f'{b:02X}' for b in value[:8])}]")
        except Exception:
            details.append(f"DID=0x{did:04X}")
        did_name = get_did_name(did)
        if did_name:
            details.append(did_name)

    detail_str = ", ".join(details) if details else ""
    return f"+{name} ({detail_str})" if detail_str else f"+{name}"


def interpret_frame(can_id, payload, ecu_filter=None):
    """Interpretuoti viena UDS kadra. Grazina (direction, ecu_name, tester_addr, text) arba None."""
    direction, _, ecu_name, tester_addr = classify_frame(can_id)
    if direction is None:
        return None

    if ecu_filter and ecu_name != ecu_filter:
        return None

    if direction == "REQ":
        text = _interpret_request(payload, ecu_name)
    else:
        text = _interpret_response(payload, ecu_name)

    if text is None:
        return None
    return direction, ecu_name, tester_addr, text


def process_log(filepath, ecu_filter=None, dtc_only=False):
    """Apdoroti visa loga su pilnu ISO-TP multi-frame surinkimu."""
    frames = load_log(filepath)
    print(f"Nuskaityta kadru: {len(frames)}\n")

    if dtc_only:
        print("=== KLAIDU (DTC) SKAITYMAS ===\n")

    reassembler = IsoTpReassembler()
    shown = 0
    sf_count = 0
    multiframe_count = 0
    skipped_fc = 0
    skipped_partial = 0

    for f in frames:
        can_id = f["can_id"]
        kind, payload = reassembler.feed(can_id, f["data"])

        if kind == "ignored":
            skipped_fc += 1
            continue
        if kind == "partial":
            skipped_partial += 1
            continue
        if kind == "error" or payload is None:
            continue

        if kind == "single":
            sf_count += 1
        elif kind == "complete":
            multiframe_count += 1

        result = interpret_frame(can_id, payload, ecu_filter)
        if result is None:
            continue

        direction, ecu_name, tester_addr, text = result

        if dtc_only and "DTC" not in text and "ReadDTCInformation" not in text and "ClearDiagnostic" not in text:
            continue

        ts = f"{f['timestamp']:10.3f}"
        arrow = ">>" if direction == "REQ" else "<<"
        # Multi-frame zinutes gali buti zymiai ilgesnes — riboju iki 32 baitu lange
        data_hex = " ".join(f"{b:02X}" for b in payload[:32])
        if len(payload) > 32:
            data_hex += f" ... (+{len(payload) - 32} baitu)"

        # Pazymeti testerio adresa tik jei jis ne F1 (Xentry default)
        tester_tag = f" [F={tester_addr:02X}]" if tester_addr != TESTER_ADDR else ""
        # Pazymeti multi-frame zinutes vizualiai
        mf_tag = " [MF]" if kind == "complete" else ""

        print(f"[{ts}] {arrow} {ecu_name:<6}{tester_tag}{mf_tag} {text}")
        print(f"             {data_hex}")
        shown += 1

    print(f"\nApdorota MP4 diagnostiniu zinuciu: {shown}")
    print(f"  Single Frame:           {sf_count}")
    print(f"  Multi-frame (sudeti):   {multiframe_count}")
    print(f"  Flow Control (ignor):   {skipped_fc}")
    print(f"  Tarpiniai FF/CF kadrai: {skipped_partial}")


def main():
    parser = argparse.ArgumentParser(description="Mercedes Actros MP4 UDS diagnostikos interpretatorius")
    parser.add_argument("logfile", help="CAN log CSV failas")
    parser.add_argument("--ecu", default=None, help="Filtruoti pagal ECU (pvz: MCM, CPC, TCM, EBS, ACM)")
    parser.add_argument("--dtc-only", action="store_true", help="Rodyti tik DTC susijusius pranesimus")
    args = parser.parse_args()

    process_log(args.logfile, args.ecu, args.dtc_only)


if __name__ == "__main__":
    main()
