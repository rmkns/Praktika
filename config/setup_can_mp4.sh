#!/bin/bash
# Mercedes-Benz Actros MP4 CAN sasajos konfiguracija
# Diagnostine CAN magistrale: 500 kbps, isplestiniai 29-bit ID (UDS/ISO-TP)
#
# Jungimas (Mercedes 14-pin sunkvezimiu jungtis arba standartine OBD-II):
#   OBD pin 6  -> CAN HAT CAN_H  (diagnostine CAN)
#   OBD pin 14 -> CAN HAT CAN_L
#   OBD pin 4  -> CAN HAT GND
#   OBD pin 16 -> +24V (DEMESIO: sunkvezimiai 24V, NE 12V! Nejunkite Pi tiesiogiai!)
#
# DEMESIO: Raspberry Pi reikia maitinti is ATSKIRO 5V saltinio (USB-C is 24V->5V step-down arba
# nesiojamo akumuliatoriaus). NEJUNKITE Pi GPIO 5V tiesiogiai prie OBD pin 16!
#
# Naudojimas: sudo ./setup_can_mp4.sh

BAUDRATE=500000

echo "=== Mercedes Actros MP4 CAN konfiguracija ==="
echo "Diagnostine CAN, $BAUDRATE bps, 29-bit ID (UDS)"

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
    echo "  candump can0                              # stebeti visa srauta"
    echo "  candump can0,18DA00F1:1FFFFFFF            # tik UDS testerio uzklausos"
    echo "  python scripts/can_logger.py --bitrate 500000"
    echo "  python scripts/mp4_interpreter.py data/logs/can_log_*.csv"
    echo ""
    echo "SVARBU: RPi prijungtas prie MP4 OBD jungties tik klausymui."
    echo "Xentry/DAS diagnostika paleidziama is atskiro kompiuterio."
    echo "RPi tik registruoja CAN srauta (pasyvus klausymas)."
else
    echo "KLAIDA: nepavyko sukonfiguruoti can0"
    exit 1
fi
