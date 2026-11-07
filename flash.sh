#!/usr/bin/env bash
# Flash CircuitPython onto the ESP32-S31-Korvo-1 over the "UART" USB-C port.
# Usage: ./flash.sh [/dev/ttyUSB0]
set -euo pipefail
cd "$(dirname "$0")"
PORT="${1:-$(ls /dev/ttyUSB* 2>/dev/null | head -1 || true)}"
[ -n "$PORT" ] || { echo "No /dev/ttyUSB* found. Plug the USB-C port labeled UART (not Power) and slide the power switch ON."; exit 1; }
BIN=$(ls firmware/adafruit-circuitpython-espressif_esp32s31_korvo_1-*.bin | sort -V | tail -1)
echo "Port: $PORT"; echo "Image: $BIN"
# Combined image (bootloader @0x2000, partition table @0x8000, app @0x10000) -> write at 0x0.
# --erase-all wipes the factory firmware first. esptool auto-enters download mode via DTR/RTS.
esptool --chip esp32s31 --port "$PORT" --baud 921600 write-flash --erase-all 0x0 "$BIN"
echo; echo "Done. Open the REPL with: ./monitor.sh $PORT"
