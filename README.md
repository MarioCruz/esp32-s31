# ESP32-S31-Korvo-1 + CircuitPython

Board: Espressif **ESP32-S31-Korvo-1 V1.1** (ESP32-S31-WROOM-3 module, 16 MB flash, 16 MB PSRAM).
CircuitPython board name: `espressif_esp32s31_korvo_1` (support added Oct 2026, first in 11.0.0-alpha.2).

## Things that are different about this board
- The S31's native USB goes to the **USB-A host jack**, so CircuitPython has **no CIRCUITPY drive**
  and no USB serial. The REPL is on **UART0 via the onboard CP2102N** = the USB-C port labeled **UART**.
- The other USB-C port (labeled **Power**) is power only. Slide the power switch to ON.
- Files get onto the board via `./put.py` (serial raw REPL, chunked with CRC32 verification). The 11.0.0-alpha.2 build has **no `wifi` module yet**, so no web workflow; `settings.toml.example` is for when a later build adds it.
- `board` exposes: `NEOPIXEL` (GPIO37), `BOOT` (GPIO61), `I2C`/`SDA`(GPIO0)/`SCL`(GPIO1),
  `TX`(GPIO58)/`RX`(GPIO59), `DISPLAY` (800x480 panel), `USB_HOST_DATA_PLUS/MINUS`.
- Audio codec is an ES8389 on I2C/I2S; CircuitPython defines no audio pins for it, so `lib/korvo1.py`
  carries the pin map and `lib/es8389.py` drives the codec (see "Audio" below).
- Camera: **not possible in CircuitPython yet.** The `espcamera` module is compiled out for the S31
  ("Library doesn't support S31 yet" in `ports/espressif/mpconfigport.mk`) and Espressif's own
  esp32-camera driver has no S31 target. Their BSP uses the newer esp_video framework instead.
  Watch for `CIRCUITPY_ESPCAMERA` being enabled for `esp32s31` in a future build.

## About the alpha CircuitPython build

This board runs **CircuitPython 11.0.0-alpha.2** (released 2026-10-21). Support for the ESP32-S31 and
the Korvo-1 landed in CircuitPython on 2026-10-13, so this is the first and so far only tagged release
that includes the board. Expect rough edges:

- **Alpha means APIs and behaviour can change** between builds. Pin the version you flash (the image in
  `firmware/` is checksummed) and re-test after upgrading.
- **Not in this build for the S31** (from `ports/espressif/mpconfigport.mk` at the 11.0.0-alpha.2 tag):
  - `wifi` and BLE ("No wifi or BLE yet"), so no web workflow, no `socketpool`, no `adafruit_requests`.
  - `espcamera` ("Library doesn't support S31 yet").
  - ADC calibration ("The IDF has no ADC calibration scheme for the S31 yet"): `analogio` readings are
    uncalibrated, which affects the PLAY/SET/VOL buttons on the resistor ladder (GPIO42).
  - `touchio` is flagged as unreliable ("Touch readings saturate at 65535 on every pad").
  - `audioio` (built-in DAC) does not exist on this chip; audio goes through the ES8389 over I2S.
- **No CIRCUITPY drive and no USB serial** is a board design fact, not an alpha limitation: the S31's only
  USB port is wired to the USB-A host jack. The workflow here is the UART REPL plus `put.py` / `run.py`.
- `I2SIn(..., external_clock=True)` raises `NotImplementedError` on the espressif port, so simultaneous
  playback and recording is not possible yet.
- Library `.mpy` files must come from the **11.x** bundle (mpy format 6). 9.x/10.x bundles fail with
  "incompatible .mpy file".

### Getting a newer build
- Releases: https://circuitpython.org/board/espressif_esp32s31_korvo_1/ (once the site lists it) or
  https://downloads.circuitpython.org/bin/espressif_esp32s31_korvo_1/en_US/
- Every merged PR is built to the S3 bucket; list them with:
  ```sh
  curl -s "https://adafruit-circuit-python.s3.amazonaws.com/?prefix=bin/espressif_esp32s31_korvo_1/en_US/&list-type=2" \
    | grep -oE "<Key>[^<]+" | sed 's/<Key>//' | tail -5
  ```
- Drop the new `.bin` into `firmware/`, update `firmware/SHA256SUMS`, run `./flash.sh` (it picks the
  highest version), then re-run `./run.py audio_test.py` to confirm the codec driver still behaves.
- Flashing erases the filesystem: push `lib/` and `code.py` again afterwards with `put.py`.

## One-time setup
```sh
sudo usermod -aG uucp $USER     # serial port access on Arch; log out/in afterwards
# or for right now only (pops a desktop password dialog):  pkexec chmod a+rw /dev/ttyUSB0
```
Tools (already installed with uv): `esptool`, `pyserial-miniterm`.

## Flash
```sh
./flash.sh                # auto-picks /dev/ttyUSB0, erases, writes firmware/*.bin at 0x0
./monitor.sh              # REPL, 115200 baud, Ctrl-] exits
```
If auto-reset into download mode fails: hold **Boot**, press and release **RST**, release Boot, rerun.

## Files in this folder
- `lib/` mirrors what is on the board's `/lib`: `neopixel.mpy` and `adafruit_display_text/` from the 11.x-mpy bundle (20261106).
- `blink.py` needs no libraries. `code.py` is the display demo.

## First program
```sh
./put.py blink.py /dev/ttyUSB0 code.py   # RGB LED cycles
for f in $(cd lib && find . -type f | sed "s|^./||"); do ./put.py lib/$f /dev/ttyUSB0 lib/$f; done   # push libs once
./put.py code.py                          # display demo (bars, text, counter, bouncing ball)
```
Libraries: `lib/` holds the needed files from the 11.x-mpy bundle (20261106). For more, download the bundle and push `.mpy` files/folders
into `/lib` with `./put.py <file> /dev/ttyUSB0 lib/<name>` (put.py creates parent folders).

## Audio (speakers + mics)
```sh
./run.py audio_test.py        # chime -> 3 s stereo recording with level trace -> playback
```
`lib/es8389.py` is a register-level driver ported from Espressif's esp_codec_dev; `lib/korvo1.py` wraps it:
```python
import korvo1, audiocore, array
codec = korvo1.codec(16000, 16)                 # open codec, configure for 16 kHz / 16-bit I2S
with korvo1.Speaker(codec, volume_db=-6) as spk:
    spk.play(audiocore.RawSample(buf, channel_count=2, sample_rate=16000)); spk.wait()
with korvo1.Microphone(codec, 16000, gain_db=30, stereo=True) as mic:
    mic.record(buf)                             # interleaved L/R int16
```
Hardware facts that matter (all learned the hard way):
- I2S: BCLK GPIO3, LRCLK GPIO4, DAC data GPIO5, ADC data GPIO6, no MCLK (codec clocks itself from BCLK).
  Amplifier enable is GPIO7 (active high). Supported rates: 8k, 16k, 44.1k, 48k (16-bit), 96k needs 32-bit.
- The ES8389 **latches its I2C address from the ADC-data pin (GPIO6) at reset**: low = 0x10, floating = 0x12.
  The driver holds GPIO6 low while resetting so the address stays 0x10, and re-scans if a write fails.
- The codec's state machine only starts once I2S clocks are present: create `I2SOut`/`I2SIn` first,
  then enable the DAC/ADC (the helpers do this and wait for state ON, ~0.15-0.3 s).
- CircuitPython's `I2SIn` on espressif does not support `external_clock`, so `I2SOut` and `I2SIn`
  cannot share BCLK/LRCLK: play and record **one at a time**, not simultaneously.
- `audiocore`, `audiomixer`, `audiomp3`, `synthio` are all built in, so MP3/WAV playback and synthesis work
  through `korvo1.Speaker`.

## Tools
- `put.py local [port] [remote]` copies a file (creates folders, CRC-verified, reloads only for code.py/boot.py).
- `run.py script.py [port] [timeout]` runs a script on the board and streams its output; code.py is untouched.
- `monitor.sh` opens the REPL.

## Newer builds
Release: https://downloads.circuitpython.org/bin/espressif_esp32s31_korvo_1/en_US/
Every PR build lands in the S3 bucket `adafruit-circuit-python` under `bin/espressif_esp32s31_korvo_1/en_US/`.
Docs: https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s31/esp32-s31-korvo-1/user_guide.html
