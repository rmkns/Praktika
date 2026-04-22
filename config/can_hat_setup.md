# RS485 CAN HAT konfiguracija Raspberry Pi

## 1. Aparatines irangos prijungimas
CAN HAT uzdedam ant Raspberry Pi GPIO header. HAT naudoja SPI sasaja:
- SPI MOSI (GPIO10)
- SPI MISO (GPIO9)
- SPI SCLK (GPIO11)
- SPI CE0 (GPIO8)
- INT (GPIO25)

CAN magistrale jungiama per varžtine jungt:
- CAN_H — CAN High
- CAN_L — CAN Low
- GND — Ground (butina!)

## 2. config.txt konfiguracija

Failo vieta priklauso nuo Raspberry Pi OS versijos:
- **Bookworm (2023-10 ir naujesne):** `/boot/firmware/config.txt`
- **Bullseye ir senesnes:** `/boot/config.txt`

Prideti eilutes failo pabaigoje:
```
dtparam=spi=on
dtoverlay=mcp2515-can0,oscillator=12000000,interrupt=25,spimaxfrequency=2000000
```

Pastaba: `oscillator` reiksme priklauso nuo HAT kristalo:
- Waveshare RS485 CAN HAT: **12 MHz** (`oscillator=12000000`)
- Kai kurie kiti HAT (pvz. Seeed): **8 MHz** (`oscillator=8000000`)

Pries pakeitimus patikrinkite savo HAT dokumentacija (kristalas pazymetas ant plokstes).

Po pakeitimu: `sudo reboot`

Pries paleidziant CAN, isitikinkite kad SPI ijungtas:
```bash
sudo raspi-config
# Interface Options -> SPI -> Enable
```

## 3. Priklausomybiu idiegimas
```bash
sudo apt update
sudo apt install can-utils
pip install -r requirements.txt   # is praktika/ saknies
```

Tai idiegs `python-can` (CAN srauto registravimui) ir `matplotlib` (grafikams).
`can-utils` paketas duoda `candump`, `cansend`, `canplayer` utilities.

## 4. Testavimas
```bash
# Sukonfiguruoti CAN sasaja (500 kbps)
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up

# Stebeti CAN srauta
candump can0

# Siusti testa kadra
cansend can0 123#DEADBEEF
```

## 5. Troubleshooting
```bash
# Patikrinti ar MCP2515 aptiktas
dmesg | grep mcp
# Turetu rodyti: mcp251x spi0.0 can0: MCP2515 successfully initialized

# Patikrinti CAN statistika
ip -statistics link show can0

# Resetinti CAN sasaja po klaidos (bus-off)
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000 restart-ms 100
sudo ip link set can0 up
```
