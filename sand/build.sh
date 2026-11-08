#!/usr/bin/env bash
# Compile the viper physics kernels for the ESP32-S31 (RISC-V rv32imc) and push them to the board.
# Needs the mpy-cross that matches the flashed CircuitPython (11.0.0-alpha.2):
#   curl -L -o sand/mpy-cross https://adafruit-circuit-python.s3.amazonaws.com/bin/mpy-cross/linux-amd64/mpy-cross-linux-amd64-11.0.0-alpha.2.static
#   chmod +x sand/mpy-cross
set -euo pipefail
cd "$(dirname "$0")/.."
MPY_CROSS="${MPY_CROSS:-sand/mpy-cross}"
[ -x "$MPY_CROSS" ] || { echo "mpy-cross not found at $MPY_CROSS (see comments in $0)"; exit 1; }
"$MPY_CROSS" --version
"$MPY_CROSS" -march=rv32imc -O2 sand/sand_viper.py -o lib/sand_viper.mpy
ls -la lib/sand_viper.mpy
PORT="${1:-/dev/ttyUSB0}"
./put.py lib/sand_viper.mpy "$PORT" lib/sand_viper.mpy
echo "now: ./run.py sand.py $PORT 60     or     ./put.py sand.py $PORT code.py"
