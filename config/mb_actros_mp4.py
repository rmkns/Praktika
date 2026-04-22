"""
Mercedes-Benz Actros MP4 (modelis 963, 2011-2018) CAN magistrales konfiguracija.
Diagnostika per OBD jungti, Xentry/DAS naudoja UDS (ISO 14229) protokola
per ISO-TP (ISO 15765-2) su 29-bit isplestiniais CAN ID.

OBD jungtis (Mercedes 14-pin sunkvezimiams arba standartine OBD-II):
  Pin 4  — GND (sasaja)
  Pin 5  — Signal GND
  Pin 6  — CAN-H (diagnostine CAN)
  Pin 14 — CAN-L
  Pin 16 — +24V (DEMESIO: sunkvezimiai naudoja 24V, ne 12V kaip lengvieji)

CAN parametrai:
  Baudrate: 500 kbps
  Kadru formatas: isplestinis 29-bit ID
  Transporto sluoksnis: ISO-TP (ISO 15765-2)
  Diagnostinis protokolas: UDS (ISO 14229-1)
"""

VEHICLE_NAME = "Mercedes-Benz Actros MP4"
TESTER_NAME = "Xentry"

CAN_BITRATE = 500000
CAN_CHANNEL = "can0"

# Mercedes Actros MP4 naudoja 29-bit isplestinius CAN ID:
#   Testeris -> ECU:  0x18DA<ECU_addr><tester_addr>
#   ECU -> Testeris:  0x18DA<tester_addr><ECU_addr>
# Pvz. CPC variklio valdiklis su Xentry (F1): request 0x18DA00F1, response 0x18DAF100
#
# Xentry/DAS naudoja 0xF1 kaip kanoninis testerio adresas, taciau realiame
# diagnostikos sraute galima pamatyti ir kitus testeriu adresus (F2-F9)
# kai jungiasi keli irankiai vienu metu arba naudojami trecios salies skaitytuvai.

TESTER_ADDR = 0xF1    # Xentry/DAS pagrindinis testerio adresas
TESTER_ADDRS = frozenset(range(0xF1, 0xFA))   # F1, F2, ..., F9 (visi galimi testeriai)


def make_request_id(ecu_addr, tester_addr=TESTER_ADDR):
    """Sukuria CAN request ID konkreciam ECU. Pagal nutyleima naudoja Xentry F1."""
    return 0x18DA0000 | (ecu_addr << 8) | tester_addr


def make_response_id(ecu_addr, tester_addr=TESTER_ADDR):
    """Sukuria CAN response ID konkreciam ECU."""
    return 0x18DA0000 | (tester_addr << 8) | ecu_addr


# Mercedes Actros MP4 ECU adresai (kaip naudoja Xentry diagnostika)
ECU_MAP = {
    0x00: {"name": "CPC",   "full": "Common Powertrain Controller (centrinis pavaru valdiklis)"},
    0x01: {"name": "MCM",   "full": "Motor Control Module (variklio valdiklis)"},
    0x03: {"name": "TCM",   "full": "Transmission Control Module (pavaru deze)"},
    0x0B: {"name": "EBS",   "full": "Electronic Brake System / ABS (stabdziu valdiklis)"},
    0x17: {"name": "INS",   "full": "Instrument Cluster (prietaisu skydelis)"},
    0x21: {"name": "ASAM",  "full": "Aftertreatment SCR ASAM (ismetamuju duju valymo modulis)"},
    0x25: {"name": "CGW",   "full": "Central Gateway (centrinis tarpinis modulis)"},
    0x2F: {"name": "CLCS",  "full": "Cab Levelling Control System (kabinos amortizacija)"},
    0x30: {"name": "EAPU",  "full": "Electronic Air Processing Unit (pneumatines sistemos valdiklis)"},
    0x34: {"name": "EIS",   "full": "Electronic Ignition Switch (uzvedimo valdiklis)"},
    0x3D: {"name": "ACM",   "full": "Aftertreatment Control Module (SCR/AdBlue valdiklis)"},
    0x7C: {"name": "MDD",   "full": "Modular Display Driver (informacinio ekrano valdiklis)"},
    0x7D: {"name": "MDP",   "full": "Modular Display Processor"},
    0x98: {"name": "MS",    "full": "Multifunction Switch (vairo jungiklis)"},
    0xE8: {"name": "VRDU",  "full": "Vehicle Restraint / Roll Detection Unit"},
}

# Atvirksitine paieska pagal ECU pavadinima
ECU_BY_NAME = {info["name"]: addr for addr, info in ECU_MAP.items()}

# Zinomi Mercedes-specifiniai DID (Data Identifiers, UDS Service 0x22)
# Standartiniai UDS DID + Daimler nuosavi
MB_DIDS = {
    # Standartiniai UDS (ISO 14229-1 Annex C)
    0xF180: "Boot Software Identification",
    0xF181: "Application Software Identification",
    0xF182: "Application Data Identification",
    0xF187: "Manufacturer Spare Part Number",
    0xF188: "ECU Software Number",
    0xF189: "ECU Software Version Number",
    0xF18A: "System Supplier Identifier",
    0xF18B: "ECU Manufacturing Date",
    0xF18C: "ECU Serial Number",
    0xF190: "VIN",
    0xF191: "ECU Hardware Number",
    0xF192: "ECU Hardware Version",
    0xF193: "System Supplier ECU Hardware Number",
    0xF194: "System Supplier ECU Software Number",
    0xF195: "System Supplier ECU Software Version",
    0xF197: "System Name or Engine Type",
    0xF198: "Repair Shop Code / Tester Serial Number",
    0xF199: "Programming Date",
    0xF19D: "ECU Installation Date",

    # Daimler MP4 specifiniai (CPC/MCM telemetrija)
    0xF1A0: "Daimler Diagnostic Variant",
    0x0405: "Engine Hours",
    0x0406: "Total Vehicle Distance",
    0x040C: "Engine Coolant Temperature",
    0x040D: "Engine Oil Temperature",
    0x0411: "Engine RPM (live)",
    0x0500: "Battery Voltage",
    0x0501: "Fuel Level (%)",
    0x0502: "AdBlue Level (%)",
    0x0600: "Total Fuel Used",
    0x0601: "Total AdBlue Used",
}

# Bendros UDS konstantos ir helperiai gyvena uds.py bibliotekoje
# (vienas saltinis visiems vehicle moduliams). Re-eksportuojam, kad
# `from mb_actros_mp4 import *` ir `get_service_name` veiktu kaip anksciau.
from uds import (
    UDS_SERVICES,
    DTC_STATUS_BITS,
    decode_service as get_service_name,
    decode_dtc_status,
)


def get_ecu_name(can_id):
    """Gauti ECU pavadinima pagal 29-bit CAN ID. Atpazista visus testerius F1-F9."""
    if not (0x18DA0000 <= can_id <= 0x18DAFFFF):
        return None

    # Request: 0x18DA<ecu><tester> -> bet kurio testerio (F1-F9) kreipinys i ECU
    if (can_id & 0xFF) in TESTER_ADDRS:
        ecu_addr = (can_id >> 8) & 0xFF
        ecu = ECU_MAP.get(ecu_addr)
        if ecu:
            return f"TX->{ecu['name']}"
        return f"TX->ECU_0x{ecu_addr:02X}"

    # Response: 0x18DA<tester><ecu> -> ECU atsakymas bet kuriam testeriui (F1-F9)
    if ((can_id >> 8) & 0xFF) in TESTER_ADDRS:
        ecu_addr = can_id & 0xFF
        ecu = ECU_MAP.get(ecu_addr)
        if ecu:
            return f"{ecu['name']}->RX"
        return f"ECU_0x{ecu_addr:02X}->RX"

    return None


def get_ecu_info(ecu_addr):
    """Gauti pilna ECU informacija."""
    return ECU_MAP.get(ecu_addr)


def get_did_name(did):
    """Gauti DID pavadinima."""
    return MB_DIDS.get(did, None)


def classify_frame(can_id):
    """
    Bendras (vehicle-agnostic) kadro klasifikatorius. Grazina:
      ("REQ",  ECU pavadinimas) — testerio uzklausa konkreciam ECU
      ("RESP", ECU pavadinimas) — ECU atsakymas testeriui
      (None, None)              — ne MP4 diagnostinis kadras

    Si funkcija leidzia full_analysis.py veikti su skirtingomis transporto
    priemonemis vienodu budu. mp4_interpreter.py turi savo platesni varianta
    (su tester_addr graza), kuris uzdengia sita imporcianti `from ... *`.
    """
    if not (0x18DA0000 <= can_id <= 0x18DAFFFF):
        return None, None

    low = can_id & 0xFF
    mid = (can_id >> 8) & 0xFF

    if low in TESTER_ADDRS:
        ecu_addr = mid
        ecu = ECU_MAP.get(ecu_addr)
        if ecu:
            return "REQ", ecu["name"]
        return "REQ", f"ECU_0x{ecu_addr:02X}"

    if mid in TESTER_ADDRS:
        ecu_addr = low
        ecu = ECU_MAP.get(ecu_addr)
        if ecu:
            return "RESP", ecu["name"]
        return "RESP", f"ECU_0x{ecu_addr:02X}"

    return None, None
