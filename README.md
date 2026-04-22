# CAN magistralės srauto analizė ir diagnostinių pranešimų interpretavimas

Projektas skirtas CAN magistralės srauto registravimui, analizei ir diagnostinių pranešimų interpretavimui naudojant Raspberry Pi su CAN HAT adapteriu.

Pagrindinės funkcijos:
- CAN srauto registravimas į CSV
- Struktūrinė ir statistinė analizė
- UDS, KWP2000 ir J1939 pranešimų interpretavimas
- DTC klaidų kodų nuskaitymas
- Grafinių ataskaitų generavimas
- Testavimas be aparatinės įrangos naudojant emuliatorių

## Palaikomos transporto priemonės

- **BMW F30 330e** — D-CAN per OBD-II, 11 bitų ID
- **Mercedes-Benz Actros MP4** — UDS per ISO-TP, 29 bitų ID
- **DAF / J1939** — J1939 ir UDS, 29 bitų ID

Naujos transporto priemonės pridėjimui pakanka:
1. sukurti failą `config/<vehicle>.py`
2. pridėti įrašą į `VEHICLE_MODULES` žodyną faile `scripts/full_analysis.py`

---

## Techninė įranga

| Komponentas | Modelis |
|---|---|
| Vienos plokštės kompiuteris | Raspberry Pi 4 arba 3B+ |
| CAN adapteris | RS485 CAN HAT (MCP2515 + SN65HVD230) |
| Sąsaja | OBD-II / sunkvežimių OBD jungtis |
| Maitinimas | USB power bank arba 12V/24V → 5V keitiklis |

CAN HAT prijungimo aprašymas: [`config/can_hat_setup.md`](config/can_hat_setup.md)

> **Svarbu:** sunkvežimių OBD jungties 16 pinas dažnai turi **+24 V**. Raspberry Pi negalima jungti tiesiogiai prie šio išvado. Naudokite atskirą 5 V maitinimo šaltinį.

---

## Programinė įranga

Reikalinga:
- Python 3.9+
- `python-can` — gyvam CAN srauto registravimui
- `matplotlib` — grafikams

Įdiegimas:

```bash
pip install -r requirements.txt
```

Pastaba: analizės ir interpretavimo skriptai gali veikti ir be `python-can`. Ši biblioteka reikalinga tik realiam srauto rinkimui.

---

## Projekto struktūra

```text
praktika/
├── config/
│   ├── can_hat_setup.md
│   ├── setup_can.sh
│   ├── setup_can_bmw.sh
│   ├── setup_can_mp4.sh
│   ├── iso_tp.py
│   ├── uds.py
│   ├── bmw_f30.py
│   └── mb_actros_mp4.py
│
├── scripts/
│   ├── can_logger.py
│   ├── bmw_logger.py
│   ├── can_analyzer.py
│   ├── bmw_interpreter.py
│   ├── mp4_interpreter.py
│   ├── diag_interpreter.py
│   ├── full_analysis.py
│   └── can_emulator.py
│
├── data/
│   ├── logs/
│   └── samples/
│
├── docs/
├── requirements.txt
└── README.md
```

---

## Greitas paleidimas

### 1. Įdiegti priklausomybes

```bash
pip install -r requirements.txt
chmod +x config/setup_can*.sh
```

### 2. Mercedes-Benz Actros MP4

```bash
sudo ./config/setup_can_mp4.sh
candump can0
python scripts/can_logger.py --bitrate 500000 --duration 60
python scripts/mp4_interpreter.py data/logs/can_log_*.csv
python scripts/full_analysis.py data/logs/can_log_*.csv --vehicle mp4
```

### 3. BMW F30

```bash
sudo ./config/setup_can_bmw.sh
python scripts/bmw_logger.py --duration 300
python scripts/bmw_interpreter.py data/logs/bmw_f30_*.csv
python scripts/full_analysis.py data/logs/bmw_f30_*.csv --vehicle bmw
```

### 4. DAF / J1939

```bash
sudo ./config/setup_can.sh 250000
python scripts/can_logger.py --bitrate 250000 --duration 60
python scripts/diag_interpreter.py data/logs/can_log_*.csv --ecu 0x0B
```

---

## `full_analysis.py` rezultatai

Skriptas sugeneruoja katalogą:

```text
results/analysis_<laikas>/
```

Jame pateikiami failai:

```text
01_strukturine_analize.txt
02_statistine_analize.txt
03_diagnostikos_srautas.txt
04_dtc_ataskaita.txt
05_ecu_informacija.txt
06_grafikai.png
pilna_ataskaita.txt
```

`full_analysis.py` gali automatiškai atpažinti transporto priemonę pagal logą, tačiau rekomenduojama naudoti `--vehicle`, kai tipas žinomas iš anksto.

---

## Skriptų paskirtis

### Srauto rinkimas

| Skriptas | Paskirtis |
|---|---|
| `can_logger.py` | Bendras CAN srauto registratorius |
| `bmw_logger.py` | BMW srauto registratorius su tiesioginiu dekodavimu |

### Analizė ir interpretavimas

| Skriptas | Paskirtis |
|---|---|
| `can_analyzer.py` | Struktūrinė ir statistinė analizė |
| `bmw_interpreter.py` | BMW diagnostinių pranešimų interpretavimas |
| `mp4_interpreter.py` | Mercedes MP4 diagnostinių pranešimų interpretavimas |
| `diag_interpreter.py` | DAF / J1939 diagnostinių pranešimų interpretavimas |
| `full_analysis.py` | Pilna analizė viena komanda |

### Testavimas

| Skriptas | Paskirtis |
|---|---|
| `can_emulator.py` | Sugeneruoja bandomąjį CAN srautą CSV formatu |

---

## Bibliotekos

### `config/iso_tp.py`

Skirta ISO-TP multi-frame pranešimų surinkimui. Palaiko:
- Single Frame
- First Frame
- Consecutive Frame
- Flow Control

Naudojama ilgesnių UDS pranešimų surinkimui iš kelių CAN kadrų.

### `config/uds.py`

Apima UDS konstantas ir pagalbines funkcijas:
- servisų pavadinimus
- NRC kodus
- sesijų tipus
- DTC subfunkcijas
- DTC statuso bitų dekodavimą

### Vehicle moduliai

Failai `config/bmw_f30.py` ir `config/mb_actros_mp4.py` aprašo konkrečios transporto priemonės:
- ECU adresus
- DID pavadinimus
- klasifikavimo logiką
- diagnostinių kadrų atpažinimą

---

## Naujos transporto priemonės pridėjimas

1. Sukurti `config/<vehicle>.py`
2. Aprašyti:
   - `VEHICLE_NAME`
   - `TESTER_NAME`
   - `ECU_MAP`
   - `classify_frame()`
   - `get_ecu_name()`
   - `get_did_name()`
3. Pridėti modulį į `VEHICLE_MODULES` žodyną faile `scripts/full_analysis.py`

---

## Multi-frame palaikymas

Kai UDS pranešimas netelpa į vieną CAN kadrą, naudojamas ISO-TP. Projektas surenka tokius pranešimus pilnai, todėl teisingai apdorojami ilgi laukai, pvz.:
- VIN
- programinės įrangos versijos
- ECU identifikatoriai

---

## Praktikos uždavinių atitikimas

| Uždavinys | Tema | Skriptai |
|---|---|---|
| 2 | Duomenų surinkimas | `can_logger.py`, `bmw_logger.py` |
| 3 | Duomenų registravimas | CSV išvestis iš tų pačių skriptų |
| 4 | Struktūrinė analizė | `can_analyzer.py`, `full_analysis.py` |
| 5 | Statistinė analizė | `can_analyzer.py`, `full_analysis.py` |
| 6 | Grafikai | `can_analyzer.py --plot`, `full_analysis.py` |
| 7 | Diagnostinių pranešimų interpretavimas | `bmw_interpreter.py`, `mp4_interpreter.py`, `diag_interpreter.py` |
| 8 | DTC klaidų kodai | `*_interpreter.py --dtc-only`, `full_analysis.py` |
| 9 | Testavimas be aparatinės įrangos | `can_emulator.py` |

---

## Pastabos

- Projektas skirtas tiek realiam CAN srauto rinkimui, tiek offline analizei.
- Analizės rezultatai išsaugomi tekstiniais failais ir paveikslėliais.
- Architektūra modulinė, todėl projektą lengva plėsti.
