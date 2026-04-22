#!/bin/bash
# BMW F30 330e CAN sasajos konfiguracija
# D-CAN magistrale: 500 kbps, standartiniai 11-bit ID
#
# Jungimas:
#   OBD pin 6  -> CAN HAT CAN_H
#   OBD pin 14 -> CAN HAT CAN_L
#   OBD pin 4  -> CAN HAT GND
#
# Naudojimas: sudo ./setup_can_bmw.sh

BAUDRATE=500000

echo "=== BMW F30 330e CAN konfiguracija ==="
echo "D-CAN magistrale, $BAUDRATE bps"

# Patikrinti MCP2515 overlay (Bookworm: /boot/firmware/config.txt; senesnes: /boot/config.txt)
CONFIG_TXT=""
for path in /boot/firmware/config.txt /boot/config.txt; do
    if [ -f "$path" ]; then
        CONFIG_TXT="$path"
        break
    fi
done

if [ -z "$CONFIG_TXT" ] || ! grep -q "mcp2515" "$CONFIG_TXT" 2>/dev/null; then
    echo ""
    echo "KLAIDA: $([ -z "$CONFIG_TXT" ] && echo "config.txt nerasta" || echo "$CONFIG_TXT") truksta MCP2515 overlay."
    echo "Pridekite:"
    echo "  dtparam=spi=on"
    echo "  dtoverlay=mcp2515-can0,oscillator=12000000,interrupt=25,spimaxfrequency=2000000"
    echo ""
    echo "Tada: sudo reboot"
    exit 1
fi

# Moduliai
sudo modprobe can
sudo modprobe can_raw
sudo modprobe mcp251x

# Konfiguracija
sudo ip link set can0 down 2>/dev/null
sudo ip link set can0 type can bitrate $BAUDRATE restart-ms 100
sudo ip link set can0 txqueuelen 1000
sudo ip link set can0 up

if ip link show can0 | grep -q "UP"; then
    echo "Paruosta! can0 @ $BAUDRATE bps"
    echo ""
    echo "Testavimas:"
    echo "  candump can0                    # stebeti srauta"
    echo "  python scripts/bmw_logger.py    # registruoti su interpretavimu"
    echo ""
    echo "SVARBU: RPi turi buti prijungtas per OBD prie BMW."
    echo "ISTA diagnostika paleidziama is atskiro kompiuterio per ENET arba ICOM."
    echo "RPi tik stebi CAN magistrale (pasyvus klausymas)."
else
    echo "KLAIDA: nepavyko sukonfiguruoti can0"
    exit 1
fi
