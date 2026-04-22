"""
BMW F30 330e (2017) CAN magistrales konfiguracija.
Diagnostika per OBD-II, ISTA naudoja D-CAN protokola (UDS over CAN).

OBD-II jungtis:
  Pin 4  — GND
  Pin 6  — CAN-H (D-CAN)
  Pin 14 — CAN-L (D-CAN)
  Pin 16 — +12V (nuolatine)

CAN parametrai:
  Baudrate: 500 kbps
  Kadru formatas: standartinis 11-bit ID
"""

VEHICLE_NAME = "BMW F30 330e"
TESTER_NAME = "ISTA"

CAN_BITRATE = 500000
CAN_CHANNEL = "can0"

# BMW F30 diagnostiniai CAN ID (D-CAN, 11-bit)
# Testeris (ISTA) -> ECU:  0x6F1 (broadcast) arba specifinis ECU adresas
# ECU -> Testeris:         0x600 + ECU_ID

TESTER_ID = 0x6F1     # ISTA testerio adresas

# BMW F30 330e ECU adresai (CAN ID = 0x600 + adresas)
ECU_MAP = {
    0x00: {"name": "DME",   "full": "Digital Motor Electronics (variklio valdiklis)", "response_id": 0x600},
    0x01: {"name": "EGS",   "full": "Elektroninis pavaru deze valdiklis",            "response_id": 0x601},
    0x02: {"name": "ABS/DSC","full": "Stabdziu / dinaminio stabilumo kontrole",      "response_id": 0x602},
    0x05: {"name": "EPS",   "full": "Elektrinis vairo ustiprinintuvas",              "response_id": 0x605},
    0x06: {"name": "ACSM",  "full": "Oro pagalviu valdiklis",                        "response_id": 0x606},
    0x07: {"name": "EME",   "full": "Elektrinis variklis (hibridine sistema)",        "response_id": 0x607},
    0x08: {"name": "SZL",   "full": "Vairo koloneles jungikliu modulis",             "response_id": 0x608},
    0x09: {"name": "SME",   "full": "HV baterijos valdiklis",                        "response_id": 0x609},
    0x10: {"name": "ZGM",   "full": "Centrinis gateway modulis",                     "response_id": 0x610},
    0x12: {"name": "CAS",   "full": "Car Access System (uzvedimo sistema)",          "response_id": 0x612},
    0x13: {"name": "JBBF",  "full": "Junction Box (kuzovo valdiklis)",               "response_id": 0x613},
    0x15: {"name": "FRM",   "full": "Footwell modulis (salono elektronika)",         "response_id": 0x615},
    0x18: {"name": "HU_NBT","full": "Head Unit (multimedija)",                       "response_id": 0x618},
    0x19: {"name": "KOMBI", "full": "Prietaisu skydelis",                            "response_id": 0x619},
    0x20: {"name": "FZD",   "full": "Stogo valdiklis",                              "response_id": 0x620},
    0x21: {"name": "IHKA",  "full": "Klimato kontrole",                             "response_id": 0x621},
    0x22: {"name": "PDC",   "full": "Parkavimo jutikliu valdiklis",                  "response_id": 0x622},
    0x28: {"name": "KAFAS", "full": "Kamera (Lane Departure, High Beam Assist)",     "response_id": 0x628},
    0x29: {"name": "ACC",   "full": "Adaptive Cruise Control (radaras)",             "response_id": 0x629},
    0x30: {"name": "EDME",  "full": "DME #2 (papildomas variklio valdiklis)",        "response_id": 0x630},
    0x38: {"name": "ICM",   "full": "iDrive valdiklis",                              "response_id": 0x638},
    0x40: {"name": "FLA",   "full": "Front Lighting Assistant",                      "response_id": 0x640},
    0x44: {"name": "GWS",   "full": "Gear selector switch",                         "response_id": 0x644},
    0x56: {"name": "TPMS",  "full": "Padangu slegio stebejimas",                    "response_id": 0x656},
    0x60: {"name": "KLE",   "full": "Ikrovimo valdiklis (plug-in charging)",         "response_id": 0x660},
    0x63: {"name": "SAS",   "full": "Stovejimo stabdzio valdiklis",                 "response_id": 0x663},
    0x72: {"name": "TRSVC", "full": "Telematic services",                            "response_id": 0x672},
}

# Zinomi BMW-specifiniai DID (Data Identifiers)
BMW_DIDS = {
    0xF190: "VIN",
    0xF191: "ECU Hardware Number",
    0xF192: "ECU Hardware Version",
    0xF193: "ECU Software Number",
    0xF194: "ECU Software Version",
    0xF195: "ECU Software Version (extended)",
    0xF19E: "ASAM/ODX File Identifier",
    0x1000: "Diagnostic Variant ID",
    0x1001: "SVK (Software Version Combination)",
    0x2504: "Coding Data",
    0x3001: "Battery Voltage",
    0x3002: "Engine RPM (live)",
    0x3003: "Coolant Temperature",
    0x3040: "HV Battery SOC (%)",
    0x3041: "HV Battery Voltage",
    0x3042: "HV Battery Current",
    0x3043: "HV Battery Temperature",
}

# Bendros DTC status bitu reiksmes ir dekoderis is uds.py bibliotekos
# (vienas saltinis visiems vehicle moduliams). Re-eksportuojam, kad
# `from bmw_f30 import *` ir tt veiktu kaip anksciau.
from uds import DTC_STATUS_BITS, decode_dtc_status


def get_ecu_name(can_id):
    """Gauti ECU pavadinima pagal CAN ID."""
    if can_id == TESTER_ID:
        return "ISTA"

    # Response ID: 0x600 + ECU_addr
    if 0x600 <= can_id <= 0x6FF:
        ecu_addr = can_id - 0x600
        ecu = ECU_MAP.get(ecu_addr)
        if ecu:
            return ecu["name"]
        return f"ECU_0x{ecu_addr:02X}"

    return None


def get_did_name(did):
    """Gauti DID pavadinima."""
    return BMW_DIDS.get(did, None)


def classify_frame(can_id):
    """
    Bendras (vehicle-agnostic) kadro klasifikatorius. Grazina:
      ("REQ",  label) — testerio uzklausa (label = TESTER_NAME)
      ("RESP", label) — ECU atsakymas (label = ECU pavadinimas)
      (None, None)    — ne diagnostinis kadras

    Si funkcija leidzia vienai analizes scenai (full_analysis.py)
    veikti su skirtingomis transporto priemonemis vienodu budu.
    """
    if can_id == TESTER_ID:
        return "REQ", TESTER_NAME

    if 0x600 <= can_id <= 0x6FF:
        ecu_addr = can_id - 0x600
        ecu = ECU_MAP.get(ecu_addr)
        if ecu:
            return "RESP", ecu["name"]
        return "RESP", f"ECU_0x{ecu_addr:02X}"

    return None, None
