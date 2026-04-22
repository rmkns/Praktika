"""
Generic UDS-over-CAN konfiguracija nezinomam transporto priemoniam.

Atitinka:
  1) VISUS 29-bit CAN ID is rangos 0x18DA0000..0x18DAFFFF
     (ISO 15765-2 normal-fixed addressing, naudojamas dauguma moderniu OEM:
      Mercedes, DAF, MAN, Iveco, Volvo, Scania ir kt.)

  2) Standartinius 11-bit OBD-II / ISO 15765-4 diagnostinius ID:
       0x7DF          — OBD-II functional request (broadcast i visus ECU)
       0x7E0..0x7E7   — OBD-II physical request  (testeris -> ECU)
       0x7E8..0x7EF   — OBD-II physical response  (ECU -> testeris)

  3) Placiu 11-bit UDS diapazonu 0x600..0x6FF, naudojamu dauguma Europiniu
     OEM (BMW D-CAN, kai kurie VAG, PSA ir kt.) kaip request/response pora.
     Testerio adresas heuristiskai nustatomas pagal zinomas pozicijas (0x6F1
     BMW ISTA, 0x6F0, 0x6FE ir kt.).

Specifiniai ECU pavadinimai NEZINOMI — kadrai pazymimi tik raw adresu baitais.
Naudoti kai capturini sraute is naujo nezinomo vehicle, kad bent matytum
diagnostiniu pranesimu strukturai (uzklausa/atsakymas, ECU adresai, UDS servisai).

`detect_vehicle()` `full_analysis.py` skripto naudoja si moduli kaip FALLBACK
po to kai bmw_f30 ir mb_actros_mp4 abu nieko neatitinka.
"""

VEHICLE_NAME = "Generic UDS (unknown vehicle)"
TESTER_NAME = "Tester"

CAN_BITRATE = 500000
CAN_CHANNEL = "can0"

# ---------------------------------------------------------------------------
# 29-bit heuristika: dauguma OEM testerio adresu yra rangoje 0xF0..0xFE
#   Mercedes Xentry/DAS: 0xF1
#   BMW ISTA (29-bit kontekstas): 0xF1
#   DAF/PACCAR/J1939: 0xF9
#   Volvo VIDA: 0xFA
#   MAN MAN-Cats: 0xFD
#
# Naudojama nustatant kuri puse yra testeris (todel kuri kryptis - REQ vs RESP).
LIKELY_TESTER_ADDRS = frozenset(range(0xF0, 0xFF))

# ---------------------------------------------------------------------------
# 11-bit: standartiniai OBD-II / ISO 15765-4 diagnostiniai ID
OBD2_FUNCTIONAL_ID = 0x7DF
OBD2_PHYS_REQ  = range(0x7E0, 0x7E8)   # 7E0-7E7: testeris -> ECU
OBD2_PHYS_RESP = range(0x7E8, 0x7F0)   # 7E8-7EF: ECU -> testeris

# 11-bit: platokas 0x600..0x6FF diapazonas (BMW D-CAN, VAG, PSA ir kt.)
# Testerio adresai: BMW naudoja 0x6F1; kiti OEM gali naudoti 0x6F0, 0x6FE ir t.t.
LIKELY_11BIT_TESTER_IDS = frozenset({0x6F0, 0x6F1, 0x6F2, 0x6FE, 0x6FF})

# Tuscias ECU map — generic neturi pavadinimu
ECU_MAP = {}
GENERIC_DIDS = {}

# Bendros UDS konstantos is uds.py bibliotekos
from uds import (
    UDS_SERVICES,
    DTC_STATUS_BITS,
    decode_service as get_service_name,
    decode_dtc_status,
)


def get_ecu_name(can_id):
    """
    Generic — pazymi raw adresais. Be specifiniu pavadinimu.
    Palaiko ir 29-bit (0x18DA) ir 11-bit (OBD-II, D-CAN) diagnostinius ID.
    """
    # 29-bit: 0x18DA range
    if 0x18DA0000 <= can_id <= 0x18DAFFFF:
        dst = (can_id >> 8) & 0xFF
        src = can_id & 0xFF
        return f"0x{dst:02X}<-0x{src:02X}"

    # 11-bit: OBD-II standard
    if can_id == OBD2_FUNCTIONAL_ID:
        return "OBD2_FUNC"
    if can_id in OBD2_PHYS_REQ:
        return f"ECU_{can_id - 0x7E0}"
    if can_id in OBD2_PHYS_RESP:
        return f"ECU_{can_id - 0x7E8}"

    # 11-bit: 0x600-0x6FF (D-CAN / European OEM)
    if 0x600 <= can_id <= 0x6FF:
        if can_id in LIKELY_11BIT_TESTER_IDS:
            return "TESTER"
        return f"ECU_0x{can_id - 0x600:02X}"

    return None


def get_did_name(did):
    """Generic neturi DID pavadinimu."""
    return None


def classify_frame(can_id):
    """
    Generic UDS klasifikatorius. Palaiko:

    1) 29-bit: 0x18DA0000..0x18DAFFFF (ISO 15765-2 normal-fixed addressing).
       Krypti (REQ vs RESP) bando atspeti is tester adreso heuristikos:
         - source (LSB) in 0xF0..0xFE -> testeris siunteja -> REQ
         - destination (byte 2) in 0xF0..0xFE -> testeris gaunatojas -> RESP

    2) 11-bit: standartiniai OBD-II / ISO 15765-4:
         0x7DF          -> REQ (functional broadcast)
         0x7E0..0x7E7   -> REQ (physical, testeris -> ECU)
         0x7E8..0x7EF   -> RESP (physical, ECU -> testeris)

    3) 11-bit: 0x600..0x6FF (D-CAN / European OEM diapazonas):
         Zinomi testerio ID (0x6F1, 0x6F0, ...) -> REQ
         Kiti -> RESP (ECU atsakymas)

    Grazina (direction, label) arba (None, None) jei ne diagnostinis.
    """
    # --- 29-bit: 0x18DA range ---
    if 0x18DA0000 <= can_id <= 0x18DAFFFF:
        dst = (can_id >> 8) & 0xFF
        src = can_id & 0xFF

        src_is_tester = src in LIKELY_TESTER_ADDRS
        dst_is_tester = dst in LIKELY_TESTER_ADDRS

        if src_is_tester and not dst_is_tester:
            return "REQ", f"ECU_0x{dst:02X}"

        if dst_is_tester and not src_is_tester:
            return "RESP", f"ECU_0x{src:02X}"

        if src_is_tester and dst_is_tester:
            return "RESP", f"ECU_0x{src:02X}"

        return "REQ", f"0x{dst:02X}<->0x{src:02X}"

    # --- 11-bit: OBD-II standard (0x7DF, 0x7E0-0x7EF) ---
    if can_id == OBD2_FUNCTIONAL_ID:
        return "REQ", "ALL_ECU"

    if can_id in OBD2_PHYS_REQ:
        ecu_n = can_id - 0x7E0
        return "REQ", f"ECU_{ecu_n}"

    if can_id in OBD2_PHYS_RESP:
        ecu_n = can_id - 0x7E8
        return "RESP", f"ECU_{ecu_n}"

    # --- 11-bit: 0x600-0x6FF (D-CAN / European OEM) ---
    if 0x600 <= can_id <= 0x6FF:
        if can_id in LIKELY_11BIT_TESTER_IDS:
            return "REQ", "TESTER"
        ecu_addr = can_id - 0x600
        return "RESP", f"ECU_0x{ecu_addr:02X}"

    return None, None
