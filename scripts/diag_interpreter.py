#!/usr/bin/env python3
"""
Diagnostiniu pranesimu interpretatorius.
Uzdaviniai 7-8: diagnostiniu pranesimu tipai, uzklausu-atsakymu modeliai,
interpretavimo metodika.

Naudojimas:
    python diag_interpreter.py data/logs/can_log.csv
    python diag_interpreter.py data/logs/can_log.csv --ecu 0x00
"""

import argparse
import csv
import os
import sys

# Bendros bibliotekos
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))
from iso_tp import IsoTpReassembler
from uds import UDS_SERVICES, DTC_SUBFUNCTIONS, decode_session, decode_nrc

# DAF/PACCAR specifiniai DID. Cia paliekam, nes diag_interpreter.py yra
# specialiai DAF/J1939 srautui (kitose vehicle config moduliuose yra savo DID).
KNOWN_DIDS = {
    0xF122: "PACCAR Software Number",
    0xF180: "BootSoftwareIdentification",
    0xF181: "ApplicationSoftwareIdentification",
    0xF186: "ActiveDiagnosticSession",
    0xF187: "VehicleManufacturerSparePartNumber",
    0xF188: "VehicleManufacturerECUHardwareNumber",
    0xF18B: "ECUManufacturingDate",
    0xF18C: "ECUSerialNumber",
    0xF190: "VIN",
    0xF191: "HardwarePartNumber",
    0xF192: "SystemSupplierECUHardwareNumber",
    0xF193: "SystemSupplierECUHardwareVersion",
    0xF194: "SystemSupplierECUSoftwareNumber",
    0xF195: "SystemSupplierECUSoftwareVersion",
    0xF197: "SystemNameOrEngineType",
}


def interpret_uds_request(service_id, data):
    """Interpretuoti UDS uzklausos duomenis."""
    name = UDS_SERVICES.get(service_id, f"Unknown(0x{service_id:02X})")
    details = ""

    if service_id == 0x10 and len(data) >= 1:  # DiagnosticSessionControl
        details = decode_session(data[0])

    elif service_id == 0x19 and len(data) >= 1:  # ReadDTCInformation
        subfunc = data[0]
        details = DTC_SUBFUNCTIONS.get(subfunc, f"0x{subfunc:02X}")
        if subfunc in (0x01, 0x02) and len(data) >= 2:
            details += f", statusMask=0x{data[1]:02X}"
        elif subfunc in (0x04, 0x06) and len(data) >= 4:
            dtc = (data[1] << 16) | (data[2] << 8) | data[3]
            details += f", DTC=0x{dtc:06X}"

    elif service_id == 0x22 and len(data) >= 2:  # ReadDataByIdentifier
        did = (data[0] << 8) | data[1]
        did_name = KNOWN_DIDS.get(did, "")
        details = f"DID=0x{did:04X}"
        if did_name:
            details += f" ({did_name})"

    elif service_id == 0x27 and len(data) >= 1:  # SecurityAccess
        if data[0] % 2 == 1:
            details = f"requestSeed (level {data[0]})"
        else:
            details = f"sendKey (level {data[0]})"

    elif service_id == 0x3E:  # TesterPresent
        details = "keepAlive"

    return name, details


def interpret_uds_response(service_id, data):
    """Interpretuoti UDS atsakymo duomenis."""
    if service_id == 0x7F and len(data) >= 2:  # Neigiamas atsakymas
        failed_sid = data[0]
        sid_name = UDS_SERVICES.get(failed_sid, f"0x{failed_sid:02X}")
        nrc_name = decode_nrc(data[1])
        return "NegativeResponse", f"{sid_name} -> {nrc_name}"

    # Teigiamas atsakymas (SID + 0x40)
    req_sid = service_id - 0x40
    name = UDS_SERVICES.get(req_sid, f"Unknown(0x{req_sid:02X})")
    details = ""

    if req_sid == 0x19 and len(data) >= 1:  # ReadDTCInformation response
        subfunc = data[0]
        if subfunc == 0x01 and len(data) >= 4:  # reportNumberOfDTCByStatusMask
            count = (data[2] << 8) | data[3]
            details = f"DTCCount={count}, availMask=0x{data[1]:02X}"
        elif subfunc == 0x02 and len(data) >= 1:  # reportDTCByStatusMask
            dtc_data_len = len(data) - 1  # minus availabilityMask
            dtc_count = dtc_data_len // 4
            details = f"{dtc_count} DTC records"

    elif req_sid == 0x22 and len(data) >= 2:  # ReadDataByIdentifier response
        did = (data[0] << 8) | data[1]
        did_name = KNOWN_DIDS.get(did, "")
        value_bytes = data[2:]
        # Bandyti interpretuoti kaip ASCII
        try:
            ascii_val = bytes(value_bytes).decode("ascii", errors="replace")
            ascii_val = ascii_val.rstrip("\x00 ")
            if ascii_val and all(c.isprintable() or c == "\x00" for c in ascii_val):
                details = f"DID=0x{did:04X} = \"{ascii_val}\""
            else:
                details = f"DID=0x{did:04X} = [{' '.join(f'{b:02X}' for b in value_bytes[:16])}]"
        except Exception:
            details = f"DID=0x{did:04X} = [{' '.join(f'{b:02X}' for b in value_bytes[:16])}]"

    return f"+{name}", details


def process_log(filepath, ecu_filter=None):
    """Apdoroti CAN loga ir interpretuoti diagnostinius pranesimu."""
    frames = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            frames.append({
                "timestamp": float(row["timestamp_s"]),
                "can_id": int(row["can_id_hex"], 16),
                "dlc": int(row["dlc"]),
                "data": bytes.fromhex(row["data_hex"].replace(" ", "")) if row["data_hex"] else b"",
                "is_extended": bool(int(row["is_extended"])),
            })

    print(f"Nuskaityta kadru: {len(frames)}")
    print()

    reassembler = IsoTpReassembler()
    sf_count = 0
    multiframe_count = 0

    for f in frames:
        can_id = f["can_id"]

        # Filtruoti pagal ECU adresa
        is_request = f["is_extended"] and (can_id & 0xFFFF00FF) == 0x18DA00F9
        is_response = f["is_extended"] and (can_id & 0xFFFFFF00) == 0x18DAF900

        if not is_request and not is_response:
            continue

        if is_request:
            ecu_addr = (can_id >> 8) & 0xFF
            direction = "REQ "
        else:
            ecu_addr = can_id & 0xFF
            direction = "RESP"

        if ecu_filter is not None and ecu_addr != ecu_filter:
            continue

        # Pamaitiniam reassembleri visais kadrais (ne tik tais kurie pereina filtra),
        # kad multi-frame busena butu islaikoma per visa loga
        kind, payload = reassembler.feed(can_id, f["data"])

        if kind in ("partial", "ignored", "error") or payload is None or len(payload) < 1:
            continue

        if kind == "single":
            sf_count += 1
        elif kind == "complete":
            multiframe_count += 1

        sid = payload[0]
        sid_data = payload[1:]

        if is_request:
            name, details = interpret_uds_request(sid, sid_data)
        else:
            name, details = interpret_uds_response(sid, sid_data)

        ts = f"{f['timestamp']:12.6f}"
        ecu_str = f"ECU 0x{ecu_addr:02X}"
        data_hex = " ".join(f"{b:02X}" for b in payload[:24])
        if len(payload) > 24:
            data_hex += f" ... (+{len(payload) - 24} baitu)"
        mf_tag = " [MF]" if kind == "complete" else ""

        detail_str = f"  ({details})" if details else ""
        print(f"[{ts}] {direction} {ecu_str}{mf_tag}  {name}{detail_str}")
        print(f"             {data_hex}")

    print(f"\nApdorota: {sf_count} SF + {multiframe_count} multi-frame zinuciu")


def main():
    parser = argparse.ArgumentParser(description="UDS/KWP diagnostiniu pranesimu interpretatorius")
    parser.add_argument("logfile", help="CAN log CSV failas")
    parser.add_argument("--ecu", default=None, help="Filtruoti pagal ECU adresa (pvz: 0x00, 0x2A)")
    args = parser.parse_args()

    ecu_filter = None
    if args.ecu:
        ecu_filter = int(args.ecu, 0)

    process_log(args.logfile, ecu_filter)


if __name__ == "__main__":
    main()
