#!/usr/bin/env python3
"""
Pilna CAN logo analize viena paleidimo.
Atlieka visus praktikos uzdavinius (4-9) automatiskai.

Naudojimas:
    python full_analysis.py data/logs/can_log_*.csv                       # default: BMW
    python full_analysis.py data/logs/bmw_f30_*.csv --vehicle bmw
    python full_analysis.py data/logs/can_log_*.csv --vehicle mp4
    python full_analysis.py data/logs/can_log_*.csv --vehicle mp4 --output-dir results/

Generuoja:
    results/analysis_<laikas>/
      01_strukturine_analize.txt     — kadru strukturine analize
      02_statistine_analize.txt      — dazniai, periodiskumas, apkrova
      03_diagnostikos_srautas.txt    — testeris <-> ECU komunikacija
      04_dtc_ataskaita.txt           — klaidu kodai (DTC) is visu ECU
      05_ecu_informacija.txt         — ECU identifikacijos duomenys (VIN, SW, HW)
      06_grafikai.png                — CAN srauto grafikai
      pilna_ataskaita.txt            — viskas viename faile
"""

import argparse
import csv
import importlib
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

# config/ katalogas i sys.path kad galetume importuoti dinamiskai
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))

# Bendros bibliotekos — iso_tp ir uds
from iso_tp import IsoTpReassembler
from uds import UDS_SERVICES, DTC_SUBFUNCTIONS, decode_session, decode_nrc

# Trumpiniai vardai -> module pavadinimai. Pridek nauja transporto priemone cia.
VEHICLE_MODULES = {
    "bmw":     "bmw_f30",
    "bmw_f30": "bmw_f30",
    "mp4":     "mb_actros_mp4",
    "mb_mp4":  "mb_actros_mp4",
    "actros":  "mb_actros_mp4",
}

# Unikalus vehicle modulu vardai (naudojama auto-detect skanavimui)
_UNIQUE_VEHICLE_MODULES = sorted(set(VEHICLE_MODULES.values()))


def load_vehicle(name):
    """Dinamiskai uzkrauti vehicle config moduli pagal trumpini."""
    module_name = VEHICLE_MODULES.get(name)
    if module_name is None:
        raise SystemExit(f"Nezinoma transporto priemone: {name}. Galimi: {sorted(set(VEHICLE_MODULES))}")
    return importlib.import_module(module_name)


def count_matches(frames, vehicle_module, sample_size=2000):
    """
    Suskaiciuoti kiek kadru is loga atpazista konkretaus vehicle modulio
    classify_frame() funkcija.

    Anksciau buvo skanuojama tik pirmieji sample_size kadru — bet dauguma
    realiu logu prasideda perdiogniu telemetrijos burtais (J1939 broadcasti)
    ir UDS diagnostine veikla atsiranda tik veliau, kai testeris pradeda
    skaityti DTC arba DID. Pvz. 8400-kadru BMW logas pirma 18DA kadra turi
    tik nuo ~3900 eilutes — pirmasis 2000 langas visiskai praleido vehicle
    klasifikatoriu.

    Sprendimas: skanuoti unikalius CAN ID is viso loga (ne kiekviena kadra
    atskirai), nes auto-detect mums rupi tik kuriuos ID atpazista
    klasifikatorius, ne kiek ju yra. Tai O(unique_ids) vietoj O(N), todel
    veikia milisekundziu greitumu net su milijonais kadru. sample_size
    parametras paliekamas API stabilumui, bet nebenaudojamas.
    """
    seen_ids = {f["can_id"] for f in frames}
    matched_ids = {can_id for can_id in seen_ids
                   if vehicle_module.classify_frame(can_id)[0] is not None}
    if not matched_ids:
        return 0
    return sum(1 for f in frames if f["can_id"] in matched_ids)


def detect_vehicle(frames):
    """
    Auto-detect vehicle is loga. Skanuoja pirmus 2000 kadru su kiekvienu zinomu
    vehicle modulio classify_frame ir grazina varda kuris atitiko daugiausiai.

    Grazina (vehicle_module, name, scores_dict) kur:
      vehicle_module — pasirinktas Python modulis
      name           — vehicle pavadinimas (VEHICLE_NAME atributas)
      scores_dict    — {module_name: match_count} visiems vehicle moduliams
    """
    scores = {}
    best = None
    best_count = -1
    best_module = None

    for module_name in _UNIQUE_VEHICLE_MODULES:
        try:
            mod = importlib.import_module(module_name)
            count = count_matches(frames, mod)
            scores[module_name] = count
            if count > best_count:
                best_count = count
                best = module_name
                best_module = mod
        except Exception as e:
            scores[module_name] = -1   # importo klaida
            continue

    return best_module, best, scores


def load_generic_fallback():
    """
    Uzkrauti generic_uds moduli — naudojamas kaip fallback kai nei vienas
    specifinis vehicle modulis (bmw_f30, mb_actros_mp4) neatpazino loga.

    generic_uds.py atpazista bet kuri 29-bit CAN ID is rangos
    0x18DA0000..0x18DAFFFF (ISO 15765-2 normal-fixed addressing), kuri yra
    standartas visiems UDS-on-CAN-Extended diagnostikos srautams nepriklausomai
    nuo OEM. ECU pavadinimai parodomi raw forma (ECU_0xNN), be vehicle-
    specifinio interpretavimo — todel report'as nemeluoja apie tai, koks
    konkrevcus vehicle yra, bet vis tiek parodo diagnostiniu kadru turini
    (UDS uzklausas/atsakymus, NRC, DID, multi-frame surinkimu).

    Si funkcija sumontuota i `main()` failure-path branche kad nesuklaidintume
    auto-detect skanavimo: generic_uds atitiktu visa daug logu kaip "match",
    todel ji sleidziame TIK kaip aiskius fallback, ne kaip eiline kandidatas.
    """
    return importlib.import_module("generic_uds")


# ============================================================================
# Duomenu nuskaitymas
# ============================================================================

def load_csv(filepath):
    frames = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data_hex = row["data_hex"].strip()
            frames.append({
                "timestamp": float(row["timestamp_s"]),
                "can_id": int(row["can_id_hex"], 16),
                "dlc": int(row["dlc"]),
                "data_hex": data_hex,
                "data": bytes.fromhex(data_hex.replace(" ", "")) if data_hex else b"",
                "is_extended": bool(int(row["is_extended"])),
            })
    return frames


def _classify(vehicle, can_id):
    """Maza obertke kuri visada grazina (direction, label) tuple."""
    return vehicle.classify_frame(can_id)


# ============================================================================
# 1. Strukturine analize (uzdavinys 4)
# ============================================================================

def strukturine_analize(frames, vehicle):
    lines = []
    lines.append("=" * 70)
    lines.append("1. STRUKTURINE ANALIZE")
    lines.append("=" * 70)

    id_counter = Counter(f["can_id"] for f in frames)
    dlc_counter = Counter(f["dlc"] for f in frames)
    ext_count = sum(1 for f in frames if f["is_extended"])
    std_count = len(frames) - ext_count

    lines.append(f"\nViso kadru: {len(frames)}")
    lines.append(f"  Standartiniai (11-bit): {std_count}")
    lines.append(f"  Isplestiniai (29-bit): {ext_count}")
    lines.append(f"Unikaliu CAN ID: {len(id_counter)}")

    lines.append(f"\nDLC pasiskirstymas:")
    for dlc in sorted(dlc_counter.keys()):
        count = dlc_counter[dlc]
        pct = count / len(frames) * 100
        bar = "#" * int(pct / 2)
        lines.append(f"  DLC={dlc}: {count:>8} ({pct:5.1f}%) {bar}")

    lines.append(f"\nVisi CAN ID (surikiuoti pagal kieki):")
    lines.append(f"  {'CAN ID':<12} {'Pavadinimas':<20} {'Kiekis':>8} {'%':>7} {'DLC':>4}")
    lines.append(f"  {'-'*55}")
    for can_id, count in id_counter.most_common():
        pct = count / len(frames) * 100
        sample = next(f for f in frames if f["can_id"] == can_id)
        _, label = _classify(vehicle, can_id)
        name = label or ""
        id_str = f"0x{can_id:03X}" if can_id <= 0x7FF else f"0x{can_id:08X}"
        lines.append(f"  {id_str:<12} {name:<20} {count:>8} {pct:>6.1f}% {sample['dlc']:>4}")

    return "\n".join(lines), id_counter


# ============================================================================
# 2. Statistine analize (uzdavinys 5)
# ============================================================================

def statistine_analize(frames, vehicle):
    lines = []
    lines.append("\n" + "=" * 70)
    lines.append("2. STATISTINE ANALIZE")
    lines.append("=" * 70)

    if len(frames) < 2:
        lines.append("Per mazai kadru analizei.")
        return "\n".join(lines)

    total_time = frames[-1]["timestamp"] - frames[0]["timestamp"]
    if total_time <= 0:
        lines.append("Registravimo trukme per trumpa.")
        return "\n".join(lines)

    avg_rate = len(frames) / total_time

    # Magistrales apkrova
    total_bits = 0
    for f in frames:
        id_bits = 29 if f["is_extended"] else 11
        total_bits += 1 + id_bits + 6 + f["dlc"] * 8 + 15 + 2 + 7 + 3

    bus_load_bps = total_bits / total_time

    lines.append(f"\nRegistravimo trukme: {total_time:.3f} s")
    lines.append(f"Viso kadru: {len(frames)}")
    lines.append(f"Vidutinis greitis: {avg_rate:.1f} kadru/s")
    lines.append(f"Magistrales apkrova: {bus_load_bps:.0f} bit/s")
    lines.append(f"  @ 250 kbps: {bus_load_bps / 250000 * 100:.1f}%")
    lines.append(f"  @ 500 kbps: {bus_load_bps / 500000 * 100:.1f}%")

    # Periodiskumo analize
    id_timestamps = defaultdict(list)
    for f in frames:
        id_timestamps[f["can_id"]].append(f["timestamp"])

    lines.append(f"\nPeriodiskumo analize:")
    lines.append(f"  {'CAN ID':<12} {'Pavadinimas':<15} {'Kiekis':>7} {'Periodas':>10} {'Min':>10} {'Max':>10} {'Jitter':>8}")
    lines.append(f"  {'-'*75}")

    sorted_ids = sorted(id_timestamps.keys(), key=lambda x: len(id_timestamps[x]), reverse=True)

    for can_id in sorted_ids:
        ts = id_timestamps[can_id]
        count = len(ts)
        _, label = _classify(vehicle, can_id)
        name = label or ""
        id_str = f"0x{can_id:03X}" if can_id <= 0x7FF else f"0x{can_id:08X}"

        if count < 3:
            lines.append(f"  {id_str:<12} {name:<15} {count:>7} {'---':>10}")
            continue

        intervals = [ts[i+1] - ts[i] for i in range(len(ts)-1)]
        avg_ms = sum(intervals) / len(intervals) * 1000
        min_ms = min(intervals) * 1000
        max_ms = max(intervals) * 1000
        # Jitter = standartinis nuokrypis
        mean = sum(intervals) / len(intervals)
        variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
        jitter_ms = (variance ** 0.5) * 1000

        lines.append(f"  {id_str:<12} {name:<15} {count:>7} {avg_ms:>8.1f}ms {min_ms:>8.1f}ms {max_ms:>8.1f}ms {jitter_ms:>6.2f}ms")

    return "\n".join(lines)


# ============================================================================
# 3. Diagnostikos srautas (uzdavinys 7)
# ============================================================================

def reassemble_uds_messages(frames):
    """
    Vienkartinis ISO-TP multi-frame surinkimas. Grazina sarisa irasai:
      [{"timestamp": float, "can_id": int, "payload": bytes, "is_multiframe": bool}, ...]

    Sis sarisas tada perduodamas i diagnostikos_srautas, dtc_ataskaita ir
    ecu_informacija — kad visiems trims butu matomos surinktos multi-frame
    zinutes (anksciau jie matydavo tik pirmas 6 baitus is FF).
    """
    reassembler = IsoTpReassembler()
    messages = []
    for f in frames:
        kind, payload = reassembler.feed(f["can_id"], f["data"])
        if kind in ("single", "complete") and payload:
            messages.append({
                "timestamp": f["timestamp"],
                "can_id": f["can_id"],
                "payload": payload,
                "is_multiframe": (kind == "complete"),
            })
    return messages


def interpret_service(vehicle, sid, data, is_request):
    """Interpretuoti viena UDS servisa is bendros uds.py bibliotekos."""
    if is_request:
        name = UDS_SERVICES.get(sid, f"SID_0x{sid:02X}")
        detail = ""

        if sid == 0x10 and len(data) >= 1:
            detail = decode_session(data[0])
        elif sid == 0x22 and len(data) >= 2:
            did = (data[0] << 8) | data[1]
            did_name = vehicle.get_did_name(did)
            detail = f"DID=0x{did:04X}" + (f" ({did_name})" if did_name else "")
        elif sid == 0x19 and len(data) >= 1:
            detail = DTC_SUBFUNCTIONS.get(data[0], f"sub=0x{data[0]:02X}")
            if data[0] in (0x01, 0x02) and len(data) >= 2:
                detail += f" mask=0x{data[1]:02X}"
        elif sid == 0x14 and len(data) >= 3:
            group = (data[0] << 16) | (data[1] << 8) | data[2]
            detail = "group=ALL" if group == 0xFFFFFF else f"group=0x{group:06X}"
        elif sid == 0x27 and len(data) >= 1:
            detail = "requestSeed" if data[0] % 2 == 1 else "sendKey"
        elif sid == 0x3E:
            detail = "keepAlive"

        return name, detail

    # Response
    if sid == 0x7F and len(data) >= 2:
        failed = UDS_SERVICES.get(data[0], f"0x{data[0]:02X}")
        nrc = decode_nrc(data[1])
        return "NEGATIVE", f"{failed} -> {nrc}"

    req_sid = sid - 0x40
    name = UDS_SERVICES.get(req_sid, f"SID_0x{req_sid:02X}")
    detail = ""

    if req_sid == 0x19 and len(data) >= 1:
        if data[0] == 0x01 and len(data) >= 4:
            count = (data[2] << 8) | data[3]
            detail = f"DTCCount={count}"
        elif data[0] == 0x02:
            dtc_count = (len(data) - 1) // 4
            detail = f"{dtc_count} DTCs"
    elif req_sid == 0x22 and len(data) >= 2:
        did = (data[0] << 8) | data[1]
        did_name = vehicle.get_did_name(did)
        value = data[2:]
        try:
            text = bytes(value).decode("ascii", errors="replace").rstrip("\x00 ")
            if text and all(c.isprintable() for c in text):
                detail = f"DID=0x{did:04X}=\"{text}\""
            else:
                detail = f"DID=0x{did:04X}=[{' '.join(f'{b:02X}' for b in value[:8])}]"
        except Exception:
            detail = f"DID=0x{did:04X}"
        if did_name:
            detail += f" ({did_name})"

    return f"+{name}", detail


def diagnostikos_srautas(uds_messages, vehicle):
    lines = []
    lines.append("\n" + "=" * 70)
    lines.append(f"3. DIAGNOSTIKOS SRAUTAS ({vehicle.TESTER_NAME} <-> ECU)")
    lines.append("=" * 70)

    diag_frames = []
    multiframe_seen = 0

    for msg in uds_messages:
        can_id = msg["can_id"]
        payload = msg["payload"]
        direction, label = _classify(vehicle, can_id)
        if direction is None:
            continue
        if len(payload) < 1:
            continue

        if msg["is_multiframe"]:
            multiframe_seen += 1

        sid = payload[0]
        is_request = (direction == "REQ")
        name, detail = interpret_service(vehicle, sid, payload[1:], is_request)
        arrow = ">>" if is_request else "<<"
        mf_tag = " [MF]" if msg["is_multiframe"] else ""

        entry = {
            "timestamp": msg["timestamp"],
            "arrow": arrow,
            "ecu": label + mf_tag,
            "name": name,
            "detail": detail,
            "hex": " ".join(f"{b:02X}" for b in payload[:24]),
        }
        diag_frames.append(entry)

    lines.append(f"\nDiagnostiniu kadru (interpretuotu): {len(diag_frames)}")
    if multiframe_seen:
        lines.append(f"  Is ju multi-frame surinkimu: {multiframe_seen}")
    lines.append("")

    # Servisu statistika
    service_counter = Counter()
    ecu_counter = Counter()
    for d in diag_frames:
        service_counter[d["name"]] += 1
        if d["arrow"] == "<<":
            ecu_counter[d["ecu"]] += 1

    lines.append("UDS servisu statistika:")
    for name, count in service_counter.most_common():
        lines.append(f"  {name:<40} {count:>6}x")

    lines.append("\nECU atsakymu statistika:")
    for ecu, count in ecu_counter.most_common():
        lines.append(f"  {ecu:<15} {count:>6} atsakymu")

    lines.append("\nPilnas diagnostinis srautas:")
    lines.append(f"  {'Laikas':>10} {'':>2} {'ECU':<10} {'Servisas':<30} {'Detales'}")
    lines.append(f"  {'-'*80}")

    for d in diag_frames:
        detail = f"  {d['detail']}" if d["detail"] else ""
        lines.append(f"  {d['timestamp']:>10.3f} {d['arrow']} {d['ecu']:<10} {d['name']:<30}{detail}")

    return "\n".join(lines), diag_frames


# ============================================================================
# 4. DTC ataskaita (uzdavinys 8)
# ============================================================================

def dtc_ataskaita(uds_messages, vehicle):
    lines = []
    lines.append("\n" + "=" * 70)
    lines.append("4. KLAIDU KODU (DTC) ATASKAITA")
    lines.append("=" * 70)

    # Surinkti DTC is 19 02 atsakymu (paima multi-frame surinktas zinutes — anksciau
    # buvo bug'as kuris matydavo tik pirmas 6 baitus is multi-frame DTC saraso)
    dtc_by_ecu = defaultdict(list)

    for msg in uds_messages:
        can_id = msg["can_id"]
        payload = msg["payload"]
        direction, label = _classify(vehicle, can_id)
        if direction != "RESP":
            continue
        if len(payload) < 4:
            continue

        # 59 02 xx ... = ReadDTCInformation response, reportDTCByStatusMask
        if payload[0] == 0x59 and payload[1] == 0x02:
            avail_mask = payload[2]
            dtc_data = payload[3:]
            dtc_count = len(dtc_data) // 4

            for i in range(dtc_count):
                offset = i * 4
                if offset + 3 >= len(dtc_data):
                    break
                d0, d1, d2, status = dtc_data[offset], dtc_data[offset+1], dtc_data[offset+2], dtc_data[offset+3]
                dtc_hex = f"{d0:02X}{d1:02X}{d2:02X}"
                status_flags = vehicle.decode_dtc_status(status)
                dtc_by_ecu[label].append({
                    "dtc": dtc_hex,
                    "status": status,
                    "flags": status_flags,
                })

        # 59 01 xx xx xx xx = count response
        elif payload[0] == 0x59 and payload[1] == 0x01 and len(payload) >= 6:
            count = (payload[4] << 8) | payload[5]
            if count == 0:
                _ = dtc_by_ecu[label]   # sukurti tuscia irasa

    if not dtc_by_ecu:
        lines.append("\nDTC duomenu nerasta loge.")
        lines.append(f"Patikrinkite ar {vehicle.TESTER_NAME} atliko klaidu skaitymaa diagnostikos metu.")
        return "\n".join(lines)

    total_dtc = sum(len(dtcs) for dtcs in dtc_by_ecu.values())
    lines.append(f"\nRasta ECU su DTC informacija: {len(dtc_by_ecu)}")
    lines.append(f"Viso klaidu kodu: {total_dtc}")

    for ecu_name in sorted(dtc_by_ecu.keys()):
        dtcs = dtc_by_ecu[ecu_name]
        lines.append(f"\n  {ecu_name}")
        lines.append(f"  {'-'*50}")

        if not dtcs:
            lines.append(f"  Klaidu nerasta (0 DTC)")
            continue

        # Deduplikacija
        seen = set()
        unique_dtcs = []
        for dtc in dtcs:
            if dtc["dtc"] not in seen:
                seen.add(dtc["dtc"])
                unique_dtcs.append(dtc)

        for dtc in unique_dtcs:
            flags = ", ".join(dtc["flags"][:3]) if dtc["flags"] else f"0x{dtc['status']:02X}"
            active = "AKTYVUS" if dtc["status"] & 0x01 else "Saugomas"
            lines.append(f"    DTC 0x{dtc['dtc']}  status=0x{dtc['status']:02X}  [{active}]  ({flags})")

    return "\n".join(lines)


# ============================================================================
# 5. ECU informacija (uzdavinys 7)
# ============================================================================

def ecu_informacija(uds_messages, vehicle):
    lines = []
    lines.append("\n" + "=" * 70)
    lines.append("5. ECU IDENTIFIKACIJOS INFORMACIJA")
    lines.append("=" * 70)

    ecu_dids = defaultdict(dict)

    for msg in uds_messages:
        can_id = msg["can_id"]
        payload = msg["payload"]
        direction, label = _classify(vehicle, can_id)
        if direction != "RESP":
            continue
        if len(payload) < 4:
            continue

        # 62 xx xx ... = ReadDataByIdentifier positive response. Multi-frame
        # surinkimas yra svarbus cia — VIN ir SW versijos daznai bunna ilgesnes
        # nei viena CAN kadras.
        if payload[0] == 0x62:
            did = (payload[1] << 8) | payload[2]
            value = payload[3:]
            did_name = vehicle.get_did_name(did) or f"DID_0x{did:04X}"

            try:
                text = bytes(value).decode("ascii", errors="replace").rstrip("\x00 ")
                if text and all(c.isprintable() for c in text):
                    ecu_dids[label][did_name] = text
                else:
                    ecu_dids[label][did_name] = " ".join(f"{b:02X}" for b in value[:32])
            except Exception:
                ecu_dids[label][did_name] = " ".join(f"{b:02X}" for b in value[:32])

    if not ecu_dids:
        lines.append("\nECU identifikacijos duomenu nerasta.")
        return "\n".join(lines)

    for ecu_name in sorted(ecu_dids.keys()):
        dids = ecu_dids[ecu_name]
        lines.append(f"\n  {ecu_name}")
        lines.append(f"  {'-'*50}")
        for did_name, value in sorted(dids.items()):
            lines.append(f"    {did_name:<35} {value}")

    return "\n".join(lines)


# ============================================================================
# 6. Grafikai (uzdavinys 5-6)
# ============================================================================

def generuoti_grafikus(frames, output_dir, vehicle):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib neidiegtas, grafikai praleidziami")
        return None

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(f"{vehicle.VEHICLE_NAME} — CAN magistrales srauto analize",
                 fontsize=14, fontweight="bold")

    id_counter = Counter(f["can_id"] for f in frames)

    # 1. Top CAN ID
    ax = axes[0][0]
    top = id_counter.most_common(15)
    labels = []
    for can_id, _ in top:
        _, label = _classify(vehicle, can_id)
        id_str = f"0x{can_id:03X}" if can_id <= 0x7FF else f"0x{can_id:08X}"
        labels.append(f"{id_str} {label}" if label else id_str)
    ax.barh(labels, [x[1] for x in top], color="#2196F3")
    ax.set_xlabel("Kadru skaicius")
    ax.set_title("Dazniausi CAN ID")
    ax.invert_yaxis()

    # 2. Kadru greitis laike
    ax = axes[0][1]
    if len(frames) > 50:
        total_time = frames[-1]["timestamp"] - frames[0]["timestamp"]
        bin_size = max(total_time / 200, 0.01)
        bins = defaultdict(int)
        for f in frames:
            bins[int(f["timestamp"] / bin_size)] += 1
        times = sorted(bins.keys())
        ax.plot([t * bin_size for t in times], [bins[t] / bin_size for t in times],
                color="#4CAF50", linewidth=0.8)
    ax.set_xlabel("Laikas (s)")
    ax.set_ylabel("Kadrai/s")
    ax.set_title("Kadru greitis laike")
    ax.grid(True, alpha=0.3)

    # 3. DLC pasiskirstymas
    ax = axes[1][0]
    dlc_counter = Counter(f["dlc"] for f in frames)
    dlcs = sorted(dlc_counter.keys())
    ax.bar(dlcs, [dlc_counter[d] for d in dlcs], color="#FF9800")
    ax.set_xlabel("DLC (duomenu ilgis)")
    ax.set_ylabel("Kiekis")
    ax.set_title("DLC pasiskirstymas")

    # 4. Diagnostiniu vs iprastu kadru santykis
    ax = axes[1][1]
    diag = sum(1 for f in frames if _classify(vehicle, f["can_id"])[0] is not None)
    other = len(frames) - diag
    if diag > 0 or other > 0:
        ax.pie([other, diag],
               labels=["Iprastas CAN srautas", "Diagnostiniai (UDS)"],
               autopct="%1.1f%%", colors=["#9E9E9E", "#F44336"])
    ax.set_title("Kadru tipai")

    plt.tight_layout()
    output_path = os.path.join(output_dir, "06_grafikai.png")
    plt.savefig(output_path, dpi=150)
    plt.close()
    return output_path


# ============================================================================
# Pagrindine programa
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Pilna CAN logo analize. Auto-detect vehicle pagal nutyleima.",
    )
    parser.add_argument("logfile", help="CAN log CSV failas (is can_logger.py arba bmw_logger.py)")
    parser.add_argument("--vehicle", default="auto",
                        choices=sorted(set(VEHICLE_MODULES.keys()) | {"auto"}),
                        help="Transporto priemones tipas (default: auto — nustatoma is loga)")
    parser.add_argument("--output-dir", default=None, help="Rezultatu katalogas (default: results/analysis_<laikas>/)")
    args = parser.parse_args()

    # Paruosti isvesties kataloga
    output_dir = args.output_dir
    if not output_dir:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"results/analysis_{ts}"
    os.makedirs(output_dir, exist_ok=True)

    # Nuskaityti
    print(f"\n[1/6] Nuskaitomas log failas...")
    frames = load_csv(args.logfile)
    print(f"       Nuskaityta: {len(frames)} kadru")

    if not frames:
        print("KLAIDA: failas tuscias")
        sys.exit(1)

    # Vehicle pasirinkimas: auto-detect arba aiskus pasirinkimas
    if args.vehicle == "auto":
        print(f"       Auto-detect vehicle is loga...")
        vehicle, detected_name, scores = detect_vehicle(frames)
        if vehicle is None or scores.get(detected_name, 0) == 0:
            print("\nDEMESIO: ne vienas specifinis vehicle modulis neatpazino sio loga.")
            print("Skanavimo rezultatai (kiek kadru atitiko klasifikatoriu):")
            for mod_name, count in sorted(scores.items(), key=lambda x: -x[1]):
                print(f"  {mod_name:<20} {count:>6}")
            vehicle = load_generic_fallback()
            print(f"\nTesiama analize naudojant fallback: {vehicle.VEHICLE_NAME}.")
            print(f"Bus parodyti visi 0x18DA0000..0x18DAFFFF diagnostiniai kadrai (raw ECU adresais),")
            print(f"taciau be specifiniu OEM ECU/DID pavadinimu. Jei vehicle yra zinomas,")
            print(f"galima rankiniu budu paleisti su --vehicle <vardas>.")
        else:
            print(f"       Detektuota: {vehicle.VEHICLE_NAME} ({scores[detected_name]} kadru tilpsta klasifikatoriaus)")
    else:
        vehicle = load_vehicle(args.vehicle)
        # Patikrinti ar pasirinktas vehicle is tikruju atitinka loga
        my_count = count_matches(frames, vehicle)
        if my_count == 0:
            # Pasirinktas vehicle visai neatitinka — paskanuoti kitus ir patarti
            print()
            print("=" * 70)
            print(f"DEMESIO: '{args.vehicle}' ({vehicle.VEHICLE_NAME}) klasifikatorius")
            print(f"NE ATITINKA NE VIENO kadro sio loga (is {min(len(frames), 2000)} skanuotu).")
            print("=" * 70)
            print()
            print("Skanavimo rezultatai pagal kitus zinomus vehicle modulius:")
            _, _, scores = detect_vehicle(frames)
            for mod_name, count in sorted(scores.items(), key=lambda x: -x[1]):
                marker = " <-- ZIA TAVO LOGAS" if count > 0 and mod_name != VEHICLE_MODULES.get(args.vehicle) else ""
                print(f"  {mod_name:<20} {count:>6} kadru atitiko{marker}")
            print()
            best = max(scores.items(), key=lambda x: x[1])
            if best[1] > 0:
                # Rasti trumpini sitam moduliui
                short_names = [k for k, v in VEHICLE_MODULES.items() if v == best[0] and k != best[0]]
                short = short_names[0] if short_names else best[0]
                print(f"Pataris: paleisk su `--vehicle {short}` (arba palik be --vehicle, auto-detect ji parinks)")
            print()
            print("Tesiama analize, taciau diagnostikos sekciai bus tuscia.")
            print()

    print(f"{'='*60}")
    print(f"  CAN MAGISTRALES SRAUTO ANALIZE")
    print(f"  {vehicle.VEHICLE_NAME} — {vehicle.TESTER_NAME} diagnostikos loggas")
    print(f"{'='*60}")
    print(f"\nIvesties failas: {args.logfile}")
    print(f"Rezultatai:      {output_dir}/")

    # Vienkartinis ISO-TP multi-frame surinkimas — naudojama trijuose vietose
    print(f"       ISO-TP surinkimas...")
    uds_messages = reassemble_uds_messages(frames)
    mf_count = sum(1 for m in uds_messages if m["is_multiframe"])
    print(f"       UDS pranesimu (po surinkimo): {len(uds_messages)} ({mf_count} multi-frame)")

    pilna_ataskaita = []
    pilna_ataskaita.append(f"CAN MAGISTRALES SRAUTO ANALIZE — {vehicle.VEHICLE_NAME}")
    pilna_ataskaita.append(f"Failas: {args.logfile}")
    pilna_ataskaita.append(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    pilna_ataskaita.append(f"Kadru: {len(frames)}")
    pilna_ataskaita.append(f"UDS pranesimu (su multi-frame surinkimu): {len(uds_messages)}")

    # Strukturine analize
    print(f"[2/6] Strukturine analize...")
    text, id_counter = strukturine_analize(frames, vehicle)
    pilna_ataskaita.append(text)
    with open(os.path.join(output_dir, "01_strukturine_analize.txt"), "w") as f:
        f.write(text)

    # Statistine analize
    print(f"[3/6] Statistine analize...")
    text = statistine_analize(frames, vehicle)
    pilna_ataskaita.append(text)
    with open(os.path.join(output_dir, "02_statistine_analize.txt"), "w") as f:
        f.write(text)

    # Diagnostikos srautas — naudoja UDS pranesimu sarisa, ne raw kadrus
    print(f"[4/6] Diagnostikos srauto analize...")
    text, diag_frames = diagnostikos_srautas(uds_messages, vehicle)
    pilna_ataskaita.append(text)
    with open(os.path.join(output_dir, "03_diagnostikos_srautas.txt"), "w") as f:
        f.write(text)

    # DTC ataskaita — taip pat is UDS pranesimu
    print(f"[5/6] Klaidu kodu (DTC) analize...")
    text = dtc_ataskaita(uds_messages, vehicle)
    pilna_ataskaita.append(text)
    with open(os.path.join(output_dir, "04_dtc_ataskaita.txt"), "w") as f:
        f.write(text)

    # ECU informacija — taip pat is UDS pranesimu
    text = ecu_informacija(uds_messages, vehicle)
    pilna_ataskaita.append(text)
    with open(os.path.join(output_dir, "05_ecu_informacija.txt"), "w") as f:
        f.write(text)

    # Grafikai — naudoja raw kadrus (ne UDS pranesimus)
    print(f"[6/6] Grafiku generavimas...")
    graph_path = generuoti_grafikus(frames, output_dir, vehicle)
    if graph_path:
        print(f"       Issaugota: {graph_path}")

    # Pilna ataskaita
    full_path = os.path.join(output_dir, "pilna_ataskaita.txt")
    with open(full_path, "w") as f:
        f.write("\n".join(pilna_ataskaita))

    # Santrauka
    diag_count = sum(1 for f in frames if _classify(vehicle, f["can_id"])[0] is not None)
    print(f"\n{'='*60}")
    print(f"  BAIGTA")
    print(f"{'='*60}")
    print(f"  Vehicle:              {vehicle.VEHICLE_NAME}")
    print(f"  Kadru:                {len(frames)}")
    print(f"  Unikaliu CAN ID:      {len(id_counter)}")
    print(f"  Diagnostiniu kadru:   {diag_count}")
    print(f"  Interpretuotu:        {len(diag_frames)}")
    print(f"\n  Rezultatai:")
    for fname in sorted(os.listdir(output_dir)):
        fpath = os.path.join(output_dir, fname)
        size = os.path.getsize(fpath)
        print(f"    {fname:<35} {size:>8} bytes")
    print()


if __name__ == "__main__":
    main()
