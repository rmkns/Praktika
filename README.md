# CAN magistrales srauto analize ir diagnostiniu pranesimu interpretavimas

Praktikos projektas — CAN magistrales srauto registravimas, strukturine ir
statistine analize, diagnostiniu pranesimu (UDS / KWP2000 / J1939) interpretavimas
naudojant Raspberry Pi su RS485 CAN HAT adapteriu.

Palaikomos transporto priemones:

- **BMW F30 330e** (D-CAN per OBD-II, 11-bit ID, ISTA testeris)
- **Mercedes-Benz Actros MP4** (29-bit UDS over ISO-TP, Xentry/DAS testeris)
- **DAF / J1939** (29-bit J1939 + UDS, F9 testeris)

Pridejimas naujos transporto priemones — viena failas `config/<vehicle>.py`
ir vienas irasas `VEHICLE_MODULES` zodyne `scripts/full_analysis.py`.

---

## Technine iranga

| Komponentas | Modelis |
|---|---|
| Vienos plokstes kompiuteris | Raspberry Pi 4 (arba 3B+) |
| CAN adapteris | RS485 CAN HAT (MCP2515 + SN65HVD230) |
| Sasaja | OBD-II / sunkvezimiu OBD jungtis |
| Maitinimas | USB power bank arba 12V/24V → 5V step-down |

Detalus aparatines irangos prijungimo aprasymas: [`config/can_hat_setup.md`](config/can_hat_setup.md).

**SVARBU sunkvezimiams (Mercedes Actros MP4 ir kt.):** OBD pin 16 yra **+24V**,
ne +12V kaip lengviems automobiliams. NEJUNKITE Pi tiesiogiai prie OBD pin 16
— maitinkite is atskiro 5V saltinio (USB power bank arba 24V→5V konverteris).

---

## Programine iranga

- Python 3.9+ (Raspberry Pi OS Bookworm pagal nutyleima)
- `python-can` — gyvas CAN srauto registravimas
- `matplotlib` — grafikai (`can_analyzer.py --plot`, `full_analysis.py`)

```bash
pip install -r requirements.txt
```

Pastaba: offline analize (`bmw_interpreter.py`, `mp4_interpreter.py`,
`diag_interpreter.py`, `can_analyzer.py`) veikia ir be `python-can` —
ji butina tik gyvai sniffinti su `can_logger.py` arba `bmw_logger.py`.

---

## Projekto struktura

```
praktika/
├── config/
│   ├── can_hat_setup.md          # CAN HAT prijungimo instrukcija
│   ├── setup_can.sh              # bendras can0 paleidimo skriptas
│   ├── setup_can_bmw.sh          # BMW-specifinis (500 kbps)
│   ├── setup_can_mp4.sh          # Mercedes MP4 (su 24V perspejimu)
│   │
│   ├── iso_tp.py                 # ISO 15765-2 multi-frame surinkimas (biblioteka)
│   ├── uds.py                    # UDS (ISO 14229) konstantos ir helperiai (biblioteka)
│   │
│   ├── bmw_f30.py                # BMW F30 vehicle config (ECU adresai, DID, etc.)
│   └── mb_actros_mp4.py          # Mercedes Actros MP4 vehicle config
│
├── scripts/
│   ├── can_logger.py             # bendras CAN srauto registratorius
│   ├── bmw_logger.py             # BMW-specifinis loggeris su live decoding
│   │
│   ├── can_analyzer.py           # strukturine + statistine analize (vehicle-agnostic)
│   ├── bmw_interpreter.py        # BMW UDS pranesimu interpretatorius
│   ├── mp4_interpreter.py        # Mercedes MP4 UDS interpretatorius (palaiko F1-F9 testerius)
│   ├── diag_interpreter.py       # DAF/J1939 UDS interpretatorius (F9 testeris)
│   │
│   ├── full_analysis.py          # PILNA praktika viena komanda (--vehicle bmw|mp4)
│   └── can_emulator.py           # bandymo duomenu generatorius (be aparatines irangos)
│
├── data/
│   ├── logs/                     # surinkti CAN logai (CSV)
│   └── samples/                  # pavyzdiniai duomenys
│
├── docs/                         # ataskaitos ir dokumentacija
├── requirements.txt
└── README.md
```

---

## Greitas paleidimas

```bash
# Idiegti priklausomybes
pip install -r requirements.txt

# Padaryti shell skriptus vykdomais (po git clone arba scp is Windows)
chmod +x config/setup_can*.sh
```

### Vienkartinis paleidimas — Mercedes MP4

```bash
# 1. Pakelti CAN sasaja (500 kbps, 29-bit ID)
sudo ./config/setup_can_mp4.sh

# 2. Patikrinti kad srautas eina
candump can0   # Ctrl-C kai pamatai kadrus

# 3. Registruoti CAN srauta
python scripts/can_logger.py --bitrate 500000 --duration 60

# 4. Interpretuoti
python scripts/mp4_interpreter.py data/logs/can_log_*.csv

# 5. Pilna ataskaita praktikos uzdaviniams (vehicle auto-detect)
python scripts/full_analysis.py data/logs/can_log_*.csv

# Arba aiskiai nurodyti vehicle:
python scripts/full_analysis.py data/logs/can_log_*.csv --vehicle mp4
```

`full_analysis.py` pagal nutyleima auto-detect-ina vehicle is loga
(skanuoja pirmus 2000 kadru su kiekvieno zinomu vehicle moduliu
`classify_frame()` ir parenka kuris atitinka daugiausiai). Jei aiskiai nurodai
neteisinga `--vehicle`, skriptas lukstai perspeja ir patarsia kuris vehicle
parametras tinka tavo logui.

Rezultatas — `results/analysis_<laikas>/` katalogas su:

```
01_strukturine_analize.txt   ← uzdavinys 4 (kadru tipai, ID, DLC)
02_statistine_analize.txt    ← uzdavinys 5 (apkrova, periodiskumas, jitter)
03_diagnostikos_srautas.txt  ← uzdavinys 7 (UDS pranesimu seka)
04_dtc_ataskaita.txt         ← uzdavinys 8 (klaidu kodai)
05_ecu_informacija.txt       ← uzdavinys 7 (VIN, SW, HW versijos)
06_grafikai.png              ← uzdavinys 5-6 (CAN srauto grafikai)
pilna_ataskaita.txt          ← visi 5 viename faile
```

### BMW F30 paleidimas

```bash
sudo ./config/setup_can_bmw.sh
python scripts/bmw_logger.py --duration 300       # registruoti 5 min su live decode
python scripts/bmw_interpreter.py data/logs/bmw_f30_*.csv
python scripts/full_analysis.py data/logs/bmw_f30_*.csv --vehicle bmw
```

### DAF / J1939 / Mercedes Actros (per F9 testeri)

```bash
sudo ./config/setup_can.sh 250000   # arba 500000, priklausomai nuo magistrales
python scripts/can_logger.py --bitrate 250000 --duration 60
python scripts/diag_interpreter.py data/logs/can_log_*.csv --ecu 0x0B
```

---

## Kiekvieno skripto trumpas aprasymas

### Surinkimas

| skriptas | pagrindas | kada naudoti |
|---|---|---|
| `can_logger.py` | bendras, vehicle-agnostic | bet kada — pirminis pasirinkimas |
| `bmw_logger.py` | BMW + live decoding | kai nori realiu laiku stebeti BMW srauta |

### Analize ir interpretavimas

| skriptas | tipas | ka daro |
|---|---|---|
| `can_analyzer.py` | strukturine + statistine | kadru ID, DLC, apkrova, periodiskumas, ISO-TP tipai (vehicle-agnostic) |
| `bmw_interpreter.py` | UDS interpretatorius | BMW F30 ISTA srautas (11-bit, 0x6F1 testeris) |
| `mp4_interpreter.py` | UDS interpretatorius | Mercedes MP4, palaiko visus F1-F9 testerius |
| `diag_interpreter.py` | UDS interpretatorius | DAF/J1939, F9 testeris |
| `full_analysis.py` | viskas viename | viso praktikos ataskaitos generavimas |

### Bandymas

| skriptas | ka daro |
|---|---|
| `can_emulator.py` | sukuria CSV su tipiniu CAN srautu — testavimui be aparatines irangos |

---

## Bibliotekos (`config/`)

Sis projektas naudoja bendras Python bibliotekas, kad kiekvienas skriptas
nereiktu parasyti tu pacios kodo. **Visa diagnostikos protokolu logika gyvena
vienoje vietoje** — pridek nauja UDS servisa ar DTC subfunkcija viename
faile, ir VISI interpretatoriai automatiskai jautis.

### `config/iso_tp.py` — ISO 15765-2 transporto sluoksnis

```python
from iso_tp import IsoTpReassembler

r = IsoTpReassembler()
for frame in frames:
    kind, payload = r.feed(frame.can_id, frame.data)
    if kind in ("single", "complete"):
        process_uds_message(payload)   # pilna zinute, multi-frame surinkta
```

Pilnai palaiko Single Frame, First Frame + Consecutive Frame multi-frame
surinkimo seka, ir Flow Control kadrus (ignoruojami).

Papildomi vieso API:

- `extract_uds_sid(data_bytes)` — be busenos, isgauna UDS Service ID
- `parse_iso_tp(data_bytes)` — be busenos, senas formatas (legacy)
- `PCI_TYPE_NAMES` — kadro tipo zmoniski pavadinimai

### `config/uds.py` — UDS (ISO 14229) konstantos

```python
from uds import UDS_SERVICES, NRC_NAMES, decode_session, decode_nrc

print(UDS_SERVICES[0x22])     # "ReadDataByIdentifier"
print(decode_nrc(0x31))       # "requestOutOfRange"
print(decode_session(0x03))   # "extended"
```

Turi:
- `UDS_SERVICES` — visi ISO 14229-1 servisu pavadinimai + KWP2000 paveldas
- `NRC_NAMES` — Negative Response kodu pavadinimai
- `SESSION_NAMES` — sesijos baitu pavadinimai (ir OEM-specifiniai: BMW, Mercedes)
- `DTC_SUBFUNCTIONS` — Service 0x19 sub-funkcijos
- `DTC_STATUS_BITS` — DTC status bitu reiksmes
- Helperiai: `decode_service`, `decode_nrc`, `decode_session`, `decode_dtc_status`

### `config/bmw_f30.py` ir `config/mb_actros_mp4.py` — vehicle moduliai

Kiekvienam transporto priemonei turi:
- `VEHICLE_NAME`, `TESTER_NAME`, `CAN_BITRATE`, `CAN_CHANNEL`
- `ECU_MAP` — adresas → ECU pavadinimas + aprasymas
- `<vehicle>_DIDS` — vehicle-specifiniai Data Identifier pavadinimai
- `classify_frame(can_id)` — nustato ar kadras yra diagnostinis ir kuria kryptimi
- `get_ecu_name`, `get_did_name`, `decode_dtc_status` (re-eksportuojama is `uds.py`)

`classify_frame` yra **bendras vehicle-agnostic interfeisas** kuris leidzia
`full_analysis.py` veikti su skirtingomis transporto priemonemis vienodu budu
(naudojant `--vehicle bmw|mp4` parametra).

### Pridejimas naujos transporto priemones

1. Sukurk `config/<vehicle>.py` su `VEHICLE_NAME`, `TESTER_NAME`, `ECU_MAP`,
   `classify_frame`, `get_ecu_name`, `get_did_name`, `decode_dtc_status`
   (paskutines dvi gali tiesiog re-eksportuoti is `uds`)
2. Pridek irasa i `VEHICLE_MODULES` zodyna `scripts/full_analysis.py:38`
3. Pasileisk: `python scripts/full_analysis.py data/logs/*.csv --vehicle <vardas>`

Daugiau nieko keisti nereikia.

---

## Multi-frame surinkimas (uzdavinys 8 papildomas)

ISO-TP UDS pranesimai daznai netilpina viename CAN kadre (8 baitai). Tada
naudojama multi-frame transmisija:

1. **First Frame** (PCI 0x1X) — turi pilnos zinutes ilgi (12 bitai) + pirmuosius 6 baitus
2. **Flow Control** (PCI 0x3X) — gavejas pasako siuntejui kiek kadrais bloko gali siusti
3. **Consecutive Frames** (PCI 0x2N) — tasinys, kiekvienas turi 7 baitus payload, sequence N=1..15

Anksciau visi projekto interpretatoriai matydavo TIK pirmus 6 baitus is
multi-frame zinutes, todel ilgesnes DID reiksmes (VIN, software versijos)
buvo nukirstos. Dabar — `IsoTpReassembler` is `iso_tp.py` surenkamas pilnu
zinutes ir interpretatoriai pazymi jas `[MF]` zenklu:

```
[   16.612] << EBS [F=F9] [MF] +ReadDataByIdentifier (DID=0xF180 = "BS5.4_v2.10_20210315_DAF...")
             62 F1 80 42 53 35 2E 34 5F 76 32 2E 31 30 5F 32 30 32 31 30 33 31 35 5F ... (+18 baitu)
```

Skripto isvesties pabaigoje rodoma kiek SF + multi-frame zinuciu surinkta.

---

## Multi-tester palaikymas (Mercedes MP4)

`mp4_interpreter.py` palaiko visus testerio adresus **F1–F9**. Pagrindinis
Xentry/DAS testeris yra `0xF1`, taciau realiame sraute galima pamatyti F2–F9
kai prijungti keli irankiai vienu metu. Kadrai is ne-F1 testeriu pazymimi
`[F=Fx]` zenklu:

```
[   12.345] >> MCM        ReadDataByIdentifier (DID=0xF190, VIN)         (Xentry F1)
[   12.401] >> CPC [F=F3] ReadDataByIdentifier (DID=0xF18C)              (kitas testeris F3)
```

---

## In-vehicle workflow (Pi sunkvezimyje)

Pi maitinamas is USB power banko, jungtas i sunkvezimio OBD per CAN HAT,
o tu sedi kabinoje su Windows lapotpu prijungtu prie Pi WiFi hotspot.

```bash
# Pi pusej (vienkartinis setup)
sudo nmcli device wifi hotspot ssid PiCAN password praktika123
sudo systemctl enable can-up.service   # auto-bring-up can0 boot metu

# Lapotpe prisijungti prie PiCAN WiFi tinkle, tada:
ssh amk@raspberrypi.local
cd ~/praktika
python scripts/can_logger.py --duration 300
python scripts/full_analysis.py data/logs/can_log_*.csv --vehicle mp4
```

Detaliai apie in-vehicle setup, screen/headless darba, ir Pi-as-hotspot:
`config/can_hat_setup.md` arba klausk `claude-code` projekto sesijoje.

---

## Praktikos uzdaviniu atitikimas

| uzd. | tema | kuris skriptas |
|---|---|---|
| 2 | duomenu surinkimas | `can_logger.py` arba `bmw_logger.py` |
| 3 | duomenu registravimas | tie patys (CSV isvestis) |
| 4 | strukturine analize | `can_analyzer.py`, `full_analysis.py` skiltys 1 |
| 5 | statistine analize | `can_analyzer.py --plot`, `full_analysis.py` skiltys 2, 6 |
| 6 | grafikai | `can_analyzer.py --plot`, `full_analysis.py` 06_grafikai.png |
| 7 | diagnostiniu pranesimu interpretavimas | `bmw_interpreter.py` / `mp4_interpreter.py` / `diag_interpreter.py` |
| 8 | klaidu kodai (DTC) | `*_interpreter.py --dtc-only`, `full_analysis.py` 04_dtc_ataskaita.txt |
| 9 | eksperimentai be aparatines irangos | `can_emulator.py` + bet kuris analizatorius |
