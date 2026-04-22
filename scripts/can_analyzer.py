#!/usr/bin/env python3
"""
CAN magistrales srauto strukturine ir statistine analize.
Uzdaviniai 4-6: kadru identifikatoriai, laiko zymos, dazniu analize,
magistrales apkrova, pranesimu pasiskirstymas.

Naudojimas:
    python can_analyzer.py data/logs/can_log.csv
    python can_analyzer.py data/logs/can_log.csv --plot
"""

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

# Bendra ISO-TP biblioteka — vienas saltinis tiesiogi visiems skriptams
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))
from iso_tp import extract_uds_sid, PCI_TYPE_NAMES


def load_csv(filepath):
    """Nuskaityti CAN log CSV faila."""
    frames = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            frames.append({
                "timestamp": float(row["timestamp_s"]),
                "can_id": row["can_id_hex"],
                "dlc": int(row["dlc"]),
                "data": row["data_hex"],
                "is_extended": bool(int(row["is_extended"])),
            })
    return frames


def structural_analysis(frames):
    """Uzdavinys 4: kadru strukturine analize."""
    print("=" * 70)
    print("STRUKTURINE ANALIZE")
    print("=" * 70)

    id_counter = Counter(f["can_id"] for f in frames)
    dlc_counter = Counter(f["dlc"] for f in frames)
    ext_count = sum(1 for f in frames if f["is_extended"])
    std_count = len(frames) - ext_count

    print(f"\nViso kadru: {len(frames)}")
    print(f"  Standartiniai (11-bit): {std_count}")
    print(f"  Isplestiniai (29-bit): {ext_count}")
    print(f"Unikaliu ID: {len(id_counter)}")

    print(f"\nDLC pasiskirstymas:")
    for dlc in sorted(dlc_counter.keys()):
        count = dlc_counter[dlc]
        pct = count / len(frames) * 100
        print(f"  DLC={dlc}: {count:>8} ({pct:5.1f}%)")

    print(f"\nDazniausiai CAN ID (top 20):")
    print(f"  {'CAN ID':<12} {'Kiekis':>8} {'%':>7} {'DLC':>4}")
    print(f"  {'-'*35}")
    for can_id, count in id_counter.most_common(20):
        pct = count / len(frames) * 100
        sample = next(f for f in frames if f["can_id"] == can_id)
        print(f"  {can_id:<12} {count:>8} {pct:>6.1f}% {sample['dlc']:>4}")

    return id_counter


def statistical_analysis(frames):
    """Uzdavinys 5: statistine analize — dazniai, periodiskumas, magistrales apkrova."""
    print("\n" + "=" * 70)
    print("STATISTINE ANALIZE")
    print("=" * 70)

    if len(frames) < 2:
        print("Per mazai kadru analizei")
        return

    total_time = frames[-1]["timestamp"] - frames[0]["timestamp"]
    if total_time <= 0:
        print("Registravimo trukme per trumpa")
        return

    avg_rate = len(frames) / total_time
    print(f"\nRegistravimo trukme: {total_time:.3f} s")
    print(f"Vidutinis kadru greitis: {avg_rate:.1f} fr/s")

    # Magistrales apkrova (bitu/s)
    total_bits = 0
    for f in frames:
        # CAN kadro bitu skaicius (apytikslis): SOF(1) + ID(11/29) + Control(6) + Data(DLC*8) + CRC(15) + ACK(2) + EOF(7) + IFS(3)
        id_bits = 29 if f["is_extended"] else 11
        total_bits += 1 + id_bits + 6 + f["dlc"] * 8 + 15 + 2 + 7 + 3

    bus_load_bps = total_bits / total_time
    bus_load_pct_250k = bus_load_bps / 250000 * 100
    bus_load_pct_500k = bus_load_bps / 500000 * 100
    print(f"Magistrales apkrova: {bus_load_bps:.0f} bit/s")
    print(f"  @ 250 kbps: {bus_load_pct_250k:.1f}%")
    print(f"  @ 500 kbps: {bus_load_pct_500k:.1f}%")

    # Periodiskumo analize per CAN ID
    id_timestamps = defaultdict(list)
    for f in frames:
        id_timestamps[f["can_id"]].append(f["timestamp"])

    print(f"\nPeriodiskumo analize (top 20 pagal kieki):")
    print(f"  {'CAN ID':<12} {'Kiekis':>7} {'Periodas':>10} {'Min':>10} {'Max':>10}")
    print(f"  {'-'*55}")

    sorted_ids = sorted(id_timestamps.keys(), key=lambda x: len(id_timestamps[x]), reverse=True)

    for can_id in sorted_ids[:20]:
        ts = id_timestamps[can_id]
        count = len(ts)
        if count < 2:
            print(f"  {can_id:<12} {count:>7} {'---':>10}")
            continue

        intervals = [ts[i+1] - ts[i] for i in range(len(ts)-1)]
        avg_interval = sum(intervals) / len(intervals)
        min_interval = min(intervals)
        max_interval = max(intervals)

        print(f"  {can_id:<12} {count:>7} {avg_interval*1000:>8.1f}ms {min_interval*1000:>8.1f}ms {max_interval*1000:>8.1f}ms")


def detect_diagnostic_frames(frames):
    """Uzdavinys 7: diagnostiniu pranesimu aptikimas."""
    print("\n" + "=" * 70)
    print("DIAGNOSTINIU PRANESIMU ANALIZE")
    print("=" * 70)

    diag_request = []
    diag_response = []

    for f in frames:
        can_id_int = int(f["can_id"], 16)
        data_bytes = bytes.fromhex(f["data"].replace(" ", "")) if f["data"] else b""

        # UDS/KWP diagnostiniai adresai (ISO 15765): 18DAxxF9 (request), 18DAF9xx (response)
        if f["is_extended"]:
            if (can_id_int & 0xFFFF00FF) == 0x18DA00F9:
                target = (can_id_int >> 8) & 0xFF
                diag_request.append({"frame": f, "target_ecu": target, "data": data_bytes})
            elif (can_id_int & 0xFFFFFF00) == 0x18DAF900:
                source = can_id_int & 0xFF
                diag_response.append({"frame": f, "source_ecu": source, "data": data_bytes})

        # Standartiniai OBD-II diagnostiniai ID (7DF broadcast, 7E0-7E7 request, 7E8-7EF response)
        if not f["is_extended"]:
            if can_id_int == 0x7DF or (0x7E0 <= can_id_int <= 0x7E7):
                diag_request.append({"frame": f, "target_ecu": can_id_int, "data": data_bytes})
            elif 0x7E8 <= can_id_int <= 0x7EF:
                diag_response.append({"frame": f, "source_ecu": can_id_int, "data": data_bytes})

    print(f"\nDiagnostiniu kadru:")
    print(f"  Uzklausos (request): {len(diag_request)}")
    print(f"  Atsakymai (response): {len(diag_response)}")

    if not diag_request and not diag_response:
        print("  Diagnostiniu pranesimu nerasta.")
        return

    # ISO-TP kadru tipu statistika (request side) — kad butu matoma kiek
    # is ju yra realios uzklausos, o kiek tik flow control / multi-frame
    pci_breakdown_req = Counter()
    service_counter = Counter()
    for req in diag_request:
        sid, pci_type = extract_uds_sid(req["data"])
        pci_breakdown_req[pci_type] += 1
        if sid is not None:
            service_counter[sid] += 1

    print(f"\nISO-TP kadru tipai (uzklausu pusej):")
    for pt in sorted(pci_breakdown_req.keys()):
        name = PCI_TYPE_NAMES.get(pt, f"Unknown(0x{pt:X})")
        print(f"  {name:<25} {pci_breakdown_req[pt]:>6}x")

    if service_counter:
        print(f"\nUDS/KWP servisai (tik kadrai su realiu SID):")
        uds_services = {
            0x10: "DiagnosticSessionControl",
            0x11: "ECUReset",
            0x14: "ClearDiagnosticInformation",
            0x19: "ReadDTCInformation",
            0x22: "ReadDataByIdentifier",
            0x23: "ReadMemoryByAddress",
            0x27: "SecurityAccess",
            0x28: "CommunicationControl",
            0x2E: "WriteDataByIdentifier",
            0x2F: "InputOutputControl",
            0x31: "RoutineControl",
            0x34: "RequestDownload",
            0x35: "RequestUpload",
            0x36: "TransferData",
            0x37: "RequestTransferExit",
            0x3D: "WriteMemoryByAddress",
            0x3E: "TesterPresent",
            0x85: "ControlDTCSetting",
            0x01: "StartCommunication (KWP)",
            0x18: "ReadDTCByStatus (KWP)",
        }
        for sid, count in service_counter.most_common():
            name = uds_services.get(sid, "Unknown")
            print(f"  0x{sid:02X} {name:<35} {count:>6}x")

    # Atsakymu pusej PCI tipu pasiskirstymas
    pci_breakdown_resp = Counter()
    response_sid_counter = Counter()
    for resp in diag_response:
        sid, pci_type = extract_uds_sid(resp["data"])
        pci_breakdown_resp[pci_type] += 1
        if sid is not None:
            response_sid_counter[sid] += 1

    print(f"\nISO-TP kadru tipai (atsakymu pusej):")
    for pt in sorted(pci_breakdown_resp.keys()):
        name = PCI_TYPE_NAMES.get(pt, f"Unknown(0x{pt:X})")
        print(f"  {name:<25} {pci_breakdown_resp[pt]:>6}x")

    if response_sid_counter:
        print(f"\nAtsakymu SID pasiskirstymas (atimti 0x40 -> uzklausos SID):")
        for sid, count in response_sid_counter.most_common(15):
            if sid == 0x7F:
                marker = "NEGATIVE"
            elif sid >= 0x40:
                req_sid = sid - 0x40
                marker = f"+{req_sid:02X}"
            else:
                marker = "?"
            print(f"  0x{sid:02X} ({marker:<10}) {count:>6}x")

    # ECU adresu statistika
    ecu_counter = Counter()
    for req in diag_request:
        if "target_ecu" in req:
            ecu_counter[req["target_ecu"]] += 1

    if ecu_counter:
        print(f"\nDiagnostuojamos ECU:")
        for ecu, count in ecu_counter.most_common():
            print(f"  ECU 0x{ecu:02X}: {count:>6} uzklausu")


def plot_analysis(frames):
    """Grafine analize."""
    try:
        import matplotlib
        # Headless Raspberry Pi (be ekrano) — naudoti Agg backend kad neuztriestu
        if not os.environ.get("DISPLAY"):
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nGrafikams reikia matplotlib: pip install matplotlib")
        return

    id_counter = Counter(f["can_id"] for f in frames)

    # 1. CAN ID pasiskirstymas
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("CAN magistrales srauto analize", fontsize=14)

    # Top 15 CAN ID
    top_ids = id_counter.most_common(15)
    ax = axes[0][0]
    ax.barh([x[0] for x in top_ids], [x[1] for x in top_ids])
    ax.set_xlabel("Kadru skaicius")
    ax.set_title("Dazniausi CAN ID")
    ax.invert_yaxis()

    # Kadru greitis laike
    ax = axes[0][1]
    if len(frames) > 100:
        bin_size = (frames[-1]["timestamp"] - frames[0]["timestamp"]) / 100
        if bin_size > 0:
            bins = defaultdict(int)
            for f in frames:
                b = int(f["timestamp"] / bin_size)
                bins[b] += 1
            times = sorted(bins.keys())
            ax.plot([t * bin_size for t in times], [bins[t] / bin_size for t in times])
    ax.set_xlabel("Laikas (s)")
    ax.set_ylabel("Kadrai/s")
    ax.set_title("Kadru greitis laike")

    # DLC pasiskirstymas
    ax = axes[1][0]
    dlc_counter = Counter(f["dlc"] for f in frames)
    dlcs = sorted(dlc_counter.keys())
    ax.bar(dlcs, [dlc_counter[d] for d in dlcs])
    ax.set_xlabel("DLC")
    ax.set_ylabel("Kiekis")
    ax.set_title("DLC pasiskirstymas")

    # Kadru tipai
    ax = axes[1][1]
    ext = sum(1 for f in frames if f["is_extended"])
    std = len(frames) - ext
    ax.pie([std, ext], labels=["Standard (11-bit)", "Extended (29-bit)"],
           autopct="%1.1f%%", colors=["#4CAF50", "#2196F3"])
    ax.set_title("Kadru tipai")

    plt.tight_layout()
    plt.savefig("data/can_analysis.png", dpi=150)
    print("\nGrafikas issaugotas: data/can_analysis.png")
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="CAN srauto analizatorius")
    parser.add_argument("logfile", help="CAN log CSV failas")
    parser.add_argument("--plot", action="store_true", help="Generuoti grafikus")
    args = parser.parse_args()

    print(f"Nuskaitomas: {args.logfile}")
    frames = load_csv(args.logfile)

    if not frames:
        print("Failas tuscias arba netinkamo formato")
        sys.exit(1)

    id_counter = structural_analysis(frames)
    statistical_analysis(frames)
    detect_diagnostic_frames(frames)

    if args.plot:
        plot_analysis(frames)


if __name__ == "__main__":
    main()
