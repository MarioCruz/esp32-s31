# ESP32-S31-Korvo-1 + CircuitPython

CircuitPython on Espressif's **ESP32-S31-Korvo-1 V1.1** (ESP32-S31-WROOM-3 module, 16 MB flash,
16 MB PSRAM, 800x480 touch LCD subboard, ES8389 audio codec, dual mics, stereo amps).
CircuitPython board name: `espressif_esp32s31_korvo_1`. Support landed in CircuitPython on
2026-10-13; the firmware here is the first tagged release that has it, **11.0.0-alpha.2**.

## Status

| Feature | State | Notes |
|---|---|---|
| Flash + REPL over the UART USB-C port | works | `flash.sh`, `monitor.sh` |
| File transfer | works | `put.py` / `run.py` over the raw REPL (no CIRCUITPY drive, see below) |
| 800x480 RGB display | works | `board.DISPLAY`, displayio, or paint the framebuffer directly |
| Touch (GT1158) | works | `lib/gt1151.py`, up to 5 fingers |
| Speakers (ES8389 + NS4150B amps) | works | `lib/es8389.py` + `korvo1.Speaker` |
| Microphones (stereo) | works | `korvo1.Microphone`; not simultaneously with playback |
| RGB LED, BOOT button | works | `neopixel`, `keypad` |
| PLAY / SET / VOL- / VOL+ buttons | partial | readable only as two pairs: no `analogio` in this build |
| Wi-Fi, BLE | no | not in the S31 port yet |
| Camera | no | `espcamera` compiled out for the S31; esp32-camera has no S31 target |
| Tilt / motion | no | the board has no accelerometer and no expansion header |
| Native USB (CIRCUITPY drive, USB serial) | no | the S31's only USB goes to the USB-A host jack by design |

## Things that are different about this board
- **No CIRCUITPY drive and no USB serial.** The REPL is UART0 through the onboard CP2102N, which is
  the USB-C port labeled **UART**. The other USB-C port (**Power**) is power only. Slide the power
  switch to ON.
- Files go to the board with `./put.py` (raw REPL, acknowledged chunks, CRC32-verified) and scripts
  run without touching `code.py` with `./run.py`.
- `board` exposes `NEOPIXEL` (GPIO37), `BOOT` (GPIO61), `I2C`/`SDA` (GPIO0)/`SCL` (GPIO1),
  `TX` (GPIO58)/`RX` (GPIO59), `DISPLAY`, `USB_HOST_DATA_PLUS/MINUS`. Everything else (I2S, amp
  enable, touch, buttons) is in `lib/korvo1.py`.
- No motion sensor of any kind, and the only connectors are the two USB-C ports, USB-A, two speaker
  ports and the LCD/camera flex cables. Physically tilting the board cannot be sensed.

## About the alpha CircuitPython build
11.0.0-alpha.2 (2026-10-21) is the first and so far only tagged release with this board. Expect
rough edges, and re-test after upgrading. From `ports/espressif/mpconfigport.mk` at that tag, the
S31 is missing:
- `wifi` and BLE ("No wifi or BLE yet"): no web workflow, `socketpool` or `adafruit_requests`.
- `espcamera` ("Library doesn't support S31 yet").
- `analogio` and `analogbufio` ("The IDF has no ADC calibration scheme for the S31 yet"), which is
  why the resistor-ladder buttons cannot be read individually.
- `touchio` ("Touch readings saturate at 65535 on every pad").
- `audioio` (no DAC on this chip): audio goes through the ES8389 over I2S.
- `I2SIn(..., external_clock=True)` is not implemented on espressif, so `I2SOut` and `I2SIn` cannot
  share clock pins: play or record, not both at once.
- On-device native/viper compilation is off, but native `.mpy` files compiled with
  `mpy-cross -march=rv32imc` load fine (`CIRCUITPY_LOAD_NATIVE` is on).
- Library `.mpy` files must come from the **11.x** bundle (mpy format 6.3). Older bundles fail with
  "incompatible .mpy file".

### Getting a newer build
- Releases: https://circuitpython.org/board/espressif_esp32s31_korvo_1/ (once listed) or
  https://downloads.circuitpython.org/bin/espressif_esp32s31_korvo_1/en_US/
- Board definition: https://github.com/adafruit/circuitpython/tree/main/ports/espressif/boards/espressif_esp32s31_korvo_1
- Espressif user guide: https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s31/esp32-s31-korvo-1/user_guide.html
- Every merged PR is built to the S3 bucket; list the newest with:
  ```sh
  curl -s "https://adafruit-circuit-python.s3.amazonaws.com/?prefix=bin/espressif_esp32s31_korvo_1/en_US/&list-type=2" \
    | grep -oE "<Key>[^<]+" | sed 's/<Key>//' | tail -5
  ```
- Drop the new `.bin` into `firmware/`, update `firmware/SHA256SUMS`, run `./flash.sh`, then push
  `lib/` and a `code.py` again (flashing erases the filesystem). If the firmware's mpy version changes,
  fetch the matching mpy-cross and rerun `sand/build.sh`.

## Setup and flashing
```sh
sudo usermod -aG uucp $USER   # serial port access on Arch; log out/in once. (Already done on this machine.)
./flash.sh                    # finds /dev/ttyUSB0, erases, writes firmware/*.bin at 0x0 via esptool
./monitor.sh                  # REPL at 115200 baud; Ctrl-] exits, Ctrl-C stops code.py, Ctrl-D reloads
```
If auto-reset into download mode fails: hold **Boot**, press and release **RST**, release Boot, rerun.
Tools are installed with `uv tool install esptool pyserial`.

## Files
| Path | What |
|---|---|
| `firmware/` | CircuitPython image + `SHA256SUMS` |
| `flash.sh`, `monitor.sh` | flash, serial REPL |
| `put.py local [port] [remote]` | copy a file to the board (creates folders, CRC-verified; reloads for code.py/boot.py/settings.toml) |
| `run.py script [port] [timeout]` | run a script on the board and stream its output; `code.py` untouched |
| `lib/korvo1.py` | pin map, `codec()`, `Speaker`, `Microphone`, `touch()`, `BootButton`, `LadderButtons` |
| `lib/es8389.py` | ES8389 codec driver (ported from Espressif's esp_codec_dev) |
| `lib/gt1151.py` | GT1151/GT1158 touch driver |
| `lib/sand_viper.mpy` | PixelDust physics, compiled for rv32imc from `sand/sand_viper.py` by `sand/build.sh` |
| `lib/neopixel.mpy`, `lib/adafruit_display_text/` | from the 11.x bundle (20261106) |
| `lib/adafruit_mpu6050.mpy`, `adafruit_lis3dh.mpy`, `adafruit_adxl34x.mpy`, `adafruit_register/` | only used if an accelerometer is wired to I2C |
| `blink.py` | LED test, no libraries needed |
| `audio_test.py` | chime, 3 s stereo recording with level trace, playback |
| `mic_meter.py` | live stereo level meter on the display |
| `touch_demo.py` | finger-painting canvas, on-screen PLAY/SET/VOL-/VOL+, BOOT clears |
| `sand.py` | PixelDust sand with touch gravity, sound and volume control (currently installed as `code.py`) |

`lib/` mirrors the board's `/lib`. To push it all once:
```sh
for f in $(cd lib && find . -type f | sed "s|^./||"); do ./put.py lib/$f /dev/ttyUSB0 lib/$f; done
```
To switch demos: `./put.py mic_meter.py /dev/ttyUSB0 code.py` (or `touch_demo.py`, `sand.py`).

## Audio (speakers + mics)
```sh
./run.py audio_test.py
```
```python
import korvo1, audiocore, array
codec = korvo1.codec(16000, 16)                 # open the ES8389, configure for 16 kHz / 16-bit I2S
with korvo1.Speaker(codec, volume_db=-6) as spk:
    spk.play(audiocore.RawSample(buf, channel_count=2, sample_rate=16000)); spk.wait()
with korvo1.Microphone(codec, 16000, gain_db=30, stereo=True) as mic:
    mic.record(buf)                             # interleaved L/R int16
```
Hardware facts that matter (all learned the hard way):
- I2S: BCLK GPIO3, LRCLK GPIO4, DAC data GPIO5, ADC data GPIO6, no MCLK (the codec clocks itself
  from BCLK). Amplifier enable is GPIO7, active high. Rates: 8k, 16k, 44.1k, 48k at 16-bit; 96k needs 32-bit.
- The ES8389 **latches its I2C address from the ADC-data pin (GPIO6) at reset**: low = 0x10,
  floating = 0x12. The driver holds GPIO6 low during reset and re-scans if a write fails.
- The codec's state machine only starts once I2S clocks are present: create the `I2SOut`/`I2SIn`
  first, then enable the DAC/ADC. The helpers do this and wait for state ON (0.15 to 0.3 s).
- `audiocore`, `audiomixer`, `audiomp3` and `synthio` are built in, so WAV/MP3 playback and synthesis
  work through `korvo1.Speaker`. A long-running demo should give the mixer a large buffer (the sand demo
  uses 16 KB) if anything blocks the main loop for more than a few ms.

## Touch screen and buttons
- **Touch**: Goodix GT1158 at I2C 0x14 on the LCD subboard. `korvo1.touch()` returns a `GT1151`
  whose `poll()` gives `(track_id, x, y, strength)` for up to 5 fingers, or `None` when there is no new
  report. Raw coordinates already match the display; `flip_x`/`flip_y`/`swap_xy` exist for other panels.
- **BOOT** (GPIO61): `korvo1.BootButton().events()` yields "pressed"/"released" via `keypad`.
- **PLAY / SET / VOL- / VOL+** share one ADC pin (GPIO42) through a resistor ladder. With no
  `analogio` in this build, `korvo1.LadderButtons()` reads the pin digitally under two pull settings
  and can tell apart only: nothing, "PLAY/SET" (low pair) and "VOL-/VOL+" (mid pair). `pressed()` is
  the debounced edge. Direct register access is blocked too (`memorymap` exposes only the RTC range).
  When a build adds `analogio`, Espressif's windows are (mV): SET 244-444, PLAY 643-843,
  VOL- 1118-1318, VOL+ 1600-1800.

## PixelDust sand demo (`sand.py`)
Port of Adafruit's [PixelDust digital sand](https://learn.adafruit.com/pixeldust-digital-sand-for-circuitpython)
(Metro RP2350 version): 3600 rainbow grains on a 200x120 grid at 4 px per grain, 30 to 60 fps.
- **Tilt**: touch the screen and the sand falls toward your finger, harder the farther from the
  centre; lift it and the sand rests at the bottom. The vector is low-pass filtered and a finger is
  dropped if the touch controller goes quiet for 0.2 s. `AUTO_ROTATE = True` restores the original's
  spinning gravity. An MPU6050/LIS3DH/ADXL34x soldered to I2C is auto-detected and used instead.
- **Sound**: a low sand hiss (filtered noise on an `audiomixer` voice) whose level follows how much
  sand moved each frame; a chime on re-scatter.
- **Buttons**: BOOT re-scatters. The VOL pair steps the volume up one notch and wraps (-30 to 0 dB);
  PLAY/SET toggles mute. A seven-segment bar along the bottom edge shows the level (red = muted);
  grains cannot enter it.
- The original's logo obstacle is left out.

Build and install (the physics must be compiled for this chip; the mpy-cross must match the firmware):
```sh
curl -L -o sand/mpy-cross https://adafruit-circuit-python.s3.amazonaws.com/bin/mpy-cross/linux-amd64/mpy-cross-linux-amd64-11.0.0-alpha.2.static
chmod +x sand/mpy-cross
./sand/build.sh                        # -> lib/sand_viper.mpy, pushed to the board
./put.py sand.py /dev/ttyUSB0 code.py
```
How it differs from the original, and why:
- `picogame` (the original's renderer) is not in this build. The viper kernels paint straight into
  the LCD's own framebuffer (`board.DISPLAY.framebuffer`, a writable RGB565 buffer whose 800-px row
  stride equals the grid at SCALE 4); `framebuffer.refresh()` is a cache write-back (~0.1 ms).
  A `displayio.Bitmap` in between cost ~26 ms per frame. displayio is parked with
  `auto_refresh = False` and an empty root group.
- No accelerometer, so touch supplies the tilt (see above).
- If the picture ever rolls (the dot-clock panel lost sync under heavy PSRAM traffic), press RST.
