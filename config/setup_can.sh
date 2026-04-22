#!/bin/bash
# Raspberry Pi CAN HAT (MCP2515) konfiguracija
#
# Paleisti su: sudo ./setup_can.sh [baudrate]
# Pvz: sudo ./setup_can.sh 250000
# Pvz: sudo ./setup_can.sh 500000

BAUDRATE=${1:-500000}

echo "=== CAN sasajos konfiguracija ==="
echo "Baudrate: $BAUDRATE bps"

# Patikrinti config.txt — Bookworm naudoja /boot/firmware/config.txt,
# senesnes Raspberry Pi OS versijos /boot/config.txt
CONFIG_TXT=""
for path in /boot/firmware/config.txt /boot/config.txt; do
    if [ -f "$path" ]; then
        CONFIG_TXT="$path"
        break
    fi
done

if [ -z "$CONFIG_TXT" ] || ! grep -q "mcp2515" "$CONFIG_TXT" 2>/dev/null; then
    echo ""
    echo "DEMESIO: $([ -z "$CONFIG_TXT" ] && echo "config.txt nerasta" || echo "$CONFIG_TXT")"
    echo "reikia prideti (i /boot/firmware/config.txt arba /boot/config.txt):"
    echo "  dtparam=spi=on"
    echo "  dtoverlay=mcp2515-can0,oscillator=12000000,interrupt=25,spimaxfrequency=2000000"
    echo ""
    echo "Pastaba: oscillator=12000000 atitinka Waveshare RS485 CAN HAT (12 MHz)."
    echo "Jei jusu HAT su 8 MHz kristalu, naudokite oscillator=8000000."
    echo ""
    echo "Po pakeitimu: sudo reboot"
    exit 1
fi

# Uzkrauti modulius
sudo modprobe can
sudo modprobe can_raw
sudo modprobe mcp251x

# Patikrinti ar MCP2515 buvo aptiktas
if ! dmesg 2>/dev/null | grep -q "mcp251x.*successfully initialized"; then
    echo "DEMESIO: MCP2515 dar neaptiktas (dmesg | grep mcp251x)."
    echo "Patikrinkite kad SPI ijungtas (sudo raspi-config -> Interface -> SPI)"
    echo "ir kad HAT teisingai uzdetas ant GPIO header."
fi

# Sukonfiguruoti can0 sasaja
sudo ip link set can0 down 2>/dev/null
# restart-ms 100: automatinis atsistatymas po bus-off klaidos
sudo ip link set can0 type can bitrate $BAUDRATE restart-ms 100
# txqueuelen 1000: standartinis 10 yra per mazas dideliam srautui
sudo ip link set can0 txqueuelen 1000
sudo ip link set can0 up

# Patikrinti
if ip link show can0 | grep -q "UP"; then
    echo "can0 sasaja sukonfiguruota sekmingai ($BAUDRATE bps)"
    ip -details link show can0
else
    echo "KLAIDA: nepavyko sukonfiguruoti can0"
    echo "  - Patikrinkite ar HAT prijungtas (lsmod | grep mcp)"
    echo "  - Patikrinkite SPI (ls /dev/spidev*)"
    echo "  - dmesg | tail -20"
    exit 1
fi
