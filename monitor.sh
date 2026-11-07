#!/usr/bin/env bash
# Serial REPL for CircuitPython (115200 baud). Ctrl-] to quit. Ctrl-C stops code.py, Ctrl-D reloads.
PORT="${1:-$(ls /dev/ttyUSB* 2>/dev/null | head -1)}"
exec pyserial-miniterm --raw "$PORT" 115200
