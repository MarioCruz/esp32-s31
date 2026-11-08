# SPDX-FileCopyrightText: 2026 Tim Cocks for Adafruit Industries (original Metro RP2350 demo)
# SPDX-License-Identifier: MIT
"""PixelDust digital sand on the ESP32-S31-Korvo-1's 800x480 display.

Port of Adafruit's "PixelDust digital sand for CircuitPython" (Metro RP2350 version):
  https://learn.adafruit.com/pixeldust-digital-sand-for-circuitpython
Physics are the unmodified viper kernels in lib/sand_viper.mpy, compiled for this chip with
  mpy-cross -march=rv32imc sand/sand_viper.py -o lib/sand_viper.mpy
Differences from the original: the picogame Scene/Canvas is replaced by the LCD's own framebuffer,
which the kernels paint directly (no displayio copy per frame), and the accelerometer (this board
has none) is replaced by the touch screen: touch anywhere and the sand falls toward your finger.
With no finger, gravity slowly rotates. BOOT re-scatters the sand (with a chime). The speakers
play a sand hiss whose loudness follows how much sand is moving.

Volume: the board's VOL-/VOL+ pair steps the volume up one notch per press and wraps around at the
top; PLAY/SET toggles mute. (This firmware has no ADC, so the four ladder buttons can only be read
as those two pairs.) A small bar along the bottom edge shows the level; grains cannot enter it.
"""
import gc, math, random, time
import board, displayio
import sand_viper
import korvo1

SCALE = 4                  # pixels per grain; 800x480 at 4 -> 200x120 cells
FILL = 0.15                # fraction of cells holding a grain
STRIPES = 6                # rainbow bands at start; 0 = scattered colours
MAX_SPEED = 5              # cells per frame
MAX_FPS = 60               # simulation steps per second (actual rate is limited by the physics step)
TILT_GAIN = 2.0            # how fast gravity reaches 1 G as the finger moves away from the centre
BACKGROUND_RGB = (0, 0, 0)


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


BACKGROUND_COLOR = rgb565(*BACKGROUND_RGB)
display = board.DISPLAY
screen_width, screen_height = display.width, display.height
GRID_WIDTH, GRID_HEIGHT = screen_width // SCALE, screen_height // SCALE
GRAIN_COUNT = int(GRID_WIDTH * GRID_HEIGHT * FILL)

# -- display: paint straight into the panel's framebuffer ---------------------------------
# board.DISPLAY is a FramebufferDisplay over a DotClockFramebuffer. That framebuffer is a writable
# RGB565 buffer with an 800-pixel row stride, which is exactly the 200-cell grid at SCALE 4, so the
# viper kernels can paint the screen directly and the per-frame displayio copy (~26 ms) disappears.
# fb.refresh() only writes the CPU cache back so the LCD DMA sees the pixels.
gc.collect()
fb = display.framebuffer
if fb.width != GRID_WIDTH * SCALE or fb.height != GRID_HEIGHT * SCALE or fb.row_stride != 2 * fb.width or fb.first_pixel_offset:
    raise RuntimeError("grid %dx%d at SCALE %d does not match framebuffer %dx%d" % (GRID_WIDTH, GRID_HEIGHT, SCALE, fb.width, fb.height))
display.auto_refresh = False          # displayio must not redraw over our pixels
display.root_group = displayio.Group()
pixels = fb
CELL_PX = SCALE

# -- sand state: same layout as sand_viper.new(), but `pixels` is the LCD framebuffer -----------
import array
grid = bytearray(GRID_WIDTH * GRID_HEIGHT)
grains = array.array("i", [0]) * (5 * GRAIN_COUNT)
BAR_W, BAR_H = 62, 2                                   # volume bar, in cells (7 segments of 8 + gaps)
BAR_X, BAR_Y = (GRID_WIDTH - BAR_W) // 2, GRID_HEIGHT - 1 - BAR_H
params = array.array("i", [0]) * (sand_viper.PARAM_BACKDROP_COLORS + BAR_W * BAR_H)
params[sand_viper.PARAM_GRID_WIDTH] = GRID_WIDTH
params[sand_viper.PARAM_GRID_HEIGHT] = GRID_HEIGHT
params[sand_viper.PARAM_GRAIN_COUNT] = GRAIN_COUNT
params[sand_viper.PARAM_CELL_SIZE] = CELL_PX
params[sand_viper.PARAM_BACKGROUND] = BACKGROUND_COLOR
params[sand_viper.PARAM_RANDOM_STATE] = random.getrandbits(30)
params[sand_viper.PARAM_JITTER_RANGE] = 1
params[sand_viper.PARAM_MAX_SPEED] = int(MAX_SPEED * 256)



def rainbow(hue):
    s = hue * 6
    sector = int(s)
    rising = int((s - sector) * 255)
    falling = 255 - rising
    r, g, b = ((255, rising, 0), (falling, 255, 0), (0, 255, rising), (0, falling, 255), (rising, 0, 255), (255, 0, falling))[sector % 6]
    return rgb565(r, g, b)


# -- volume bar: a strip of obstacle cells the kernels never repaint, so we can draw on it ----
VOLUME_STEPS = (-30, -24, -18, -12, -8, -4, 0)         # dB, cycled by the VOL buttons
VOLUME_DB = -8
volume_index = VOLUME_STEPS.index(VOLUME_DB)
muted = False
fb_pixels = memoryview(fb)                             # 'H' view of the RGB565 framebuffer
BAR_ON, BAR_OFF, BAR_MUTE = rgb565(40, 210, 90), rgb565(45, 50, 70), rgb565(230, 60, 50)


def bar_colors():
    cols = []
    for row in range(BAR_H):
        for col in range(BAR_W):
            seg, pos = divmod(col, 9)                   # 8 lit cells then a 1-cell gap
            if pos == 8:
                cols.append(BACKGROUND_COLOR)
            elif muted:
                cols.append(BAR_MUTE)
            else:
                cols.append(BAR_ON if seg <= volume_index else BAR_OFF)
    return cols


sand_viper.backdrop(grid, params, BAR_X, BAR_Y, BAR_W, BAR_H, bar_colors(), bytes([1]) * (BAR_W * BAR_H))


def paint_bar():
    cols = bar_colors()
    stride = fb.width
    for i, color in enumerate(cols):
        params[sand_viper.PARAM_BACKDROP_COLORS + i] = color
        row, col = divmod(i, BAR_W)
        px, py = (BAR_X + col) * SCALE, (BAR_Y + row) * SCALE
        for dy in range(SCALE):
            base = (py + dy) * stride + px
            for dx in range(SCALE):
                fb_pixels[base + dx] = color


def scatter():
    if STRIPES:
        saved = params[sand_viper.PARAM_RANDOM_STATE]
        sand_viper.place(grains, grid, pixels, params)
        for i in range(GRAIN_COUNT):
            stripe = (grains[5 * i + 1] >> 8) * STRIPES // GRID_HEIGHT
            grains[5 * i + 4] = rainbow(stripe / max(STRIPES - 1, 1) * 5 / 6)
        params[sand_viper.PARAM_RANDOM_STATE] = saved
    else:
        for i in range(GRAIN_COUNT):
            grains[5 * i + 4] = rainbow(i / GRAIN_COUNT)
    sand_viper.place(grains, grid, pixels, params)
    paint_bar()
    fb.refresh()


scatter()

# -- sound: a sand hiss that follows how much is moving, and a chime on re-scatter -----------
import audiocore, audiomixer
from ulab import numpy as np
AUDIO_RATE = 16000


def noise_sample(seconds=1.0):
    """Stereo 'brown-ish' noise: white noise through a one-pole low-pass, which sounds like sand."""
    n = int(AUDIO_RATE * seconds)
    out = array.array("h", [0] * (2 * n))
    for ch in range(2):
        acc = 0.0
        for i in range(n):
            acc += (random.random() - 0.5) * 0.35 - acc * 0.12
            out[2 * i + ch] = int(max(-1.0, min(1.0, acc * 3)) * 24000)
    return audiocore.RawSample(out, channel_count=2, sample_rate=AUDIO_RATE)


def chime_sample():
    n = int(AUDIO_RATE * 0.25)
    t = np.arange(n) / AUDIO_RATE
    env = np.minimum(np.minimum(np.arange(n) / 200, (n - np.arange(n)) / 1200), 1.0)
    mono = env * (np.sin(2 * np.pi * 880 * t) * 0.6 + np.sin(2 * np.pi * 1320 * t) * 0.4) * 12000
    st = np.zeros(2 * n); st[0::2] = mono; st[1::2] = mono
    return audiocore.RawSample(array.array("h", np.array(st, dtype=np.int16)), channel_count=2, sample_rate=AUDIO_RATE)


codec = korvo1.codec(AUDIO_RATE, 16)
speaker = korvo1.Speaker(codec, VOLUME_DB).__enter__()
# Big mixer buffer: the viper step blocks for 12-20 ms and audio is only refilled between frames.
mixer = audiomixer.Mixer(voice_count=2, sample_rate=AUDIO_RATE, channel_count=2, bits_per_sample=16, samples_signed=True, buffer_size=16384)
hiss = noise_sample()
chime = chime_sample()
speaker.play(mixer)
mixer.voice[0].level = 0.0
mixer.voice[0].play(hiss, loop=True)
hiss_level = 0.0
ladder = korvo1.LadderButtons()


def apply_volume(announce=True):
    codec.dac_volume(-95.5 if muted else VOLUME_STEPS[volume_index])
    paint_bar()
    fb.refresh()
    if announce and not muted:
        mixer.voice[1].play(chime)
    print("volume:", "muted" if muted else "%d dB" % VOLUME_STEPS[volume_index])


# -- "accelerometer": touch screen, or slowly rotating gravity -----------------------------
touch = korvo1.touch()
boot = korvo1.BootButton()
GRAVITY_UNITS = 32          # 1 G in the kernel's units (raw 4 G counts / 256)
finger = None


def read_acceleration():
    """(accel_x, accel_y, jitter_range) in grain units per frame, like the original."""
    if finger:
        fx = (finger[0] - screen_width / 2) / (screen_width / 2)     # -1 .. 1
        fy = (finger[1] - screen_height / 2) / (screen_height / 2)
        mag = min(1.0, math.sqrt(fx * fx + fy * fy) * TILT_GAIN)
        ang = math.atan2(fy, fx)
        ax, ay = math.cos(ang) * mag, math.sin(ang) * mag
        flat = 1.0 - mag
    else:
        angle = time.monotonic() * 0.4
        ax, ay, flat = 0.9 * math.cos(angle), -0.9 * math.sin(angle), 0.45
    flatness = int(abs(flat) * 4)
    jitter = 1 if flatness >= 3 else 4 - flatness
    return int(ax * GRAVITY_UNITS) - jitter, int(ay * GRAVITY_UNITS) - jitter, 2 * jitter + 1


print("%dx%d, %d grains on %dx%d cells, viper arch ok" % (screen_width, screen_height, GRAIN_COUNT, GRID_WIDTH, GRID_HEIGHT))
frame_ns = 1000000000 // MAX_FPS
next_frame_ns = time.monotonic_ns()
frames = step_ns = draw_ns = 0
report_ns = next_frame_ns + 2000000000
poll_every = 2
n = 0
while True:
    n += 1
    if n % poll_every == 0:                       # touch poll is ~1 ms of I2C; not every frame
        pts = touch.poll()
        if pts is not None:
            finger = (pts[0][1], pts[0][2]) if pts else None
    for ev in boot.events():
        if ev == "pressed":
            mixer.voice[1].play(chime)
            scatter()
    group = ladder.pressed()                          # debounced: "VOL-/VOL+", "PLAY/SET" or None
    if group == "VOL-/VOL+":
        muted = False
        volume_index = (volume_index + 1) % len(VOLUME_STEPS)
        apply_volume()
    elif group == "PLAY/SET":
        muted = not muted
        apply_volume()
    accel_x, accel_y, jitter_range = read_acceleration()
    params[sand_viper.PARAM_ACCEL_X] = accel_x
    params[sand_viper.PARAM_ACCEL_Y] = accel_y
    params[sand_viper.PARAM_JITTER_RANGE] = jitter_range

    t0 = time.monotonic_ns()
    moved = sand_viper.step(grains, grid, pixels, params)   # paints moved grains straight into the framebuffer
    t1 = time.monotonic_ns()
    fb.refresh()                                       # cache write-back so the LCD DMA sees them
    # hiss volume follows the share of grains that moved this frame, smoothed so it swells and fades
    target = min(1.0, (moved / GRAIN_COUNT) * 2.5)
    hiss_level += (target - hiss_level) * (0.25 if target > hiss_level else 0.08)
    mixer.voice[0].level = hiss_level
    t2 = time.monotonic_ns()
    frames += 1; step_ns += t1 - t0; draw_ns += t2 - t1
    if t2 >= report_ns:
        print("%d fps, step %d us, draw %d us, gravity (%d, %d)%s, hiss %.2f, audio %s" % (frames // 2, step_ns // frames // 1000, draw_ns // frames // 1000,
                                                                       accel_x, accel_y, " finger" if finger else "", hiss_level, "playing" if speaker.out.playing else "STOPPED"))
        frames = step_ns = draw_ns = 0
        report_ns += 2000000000
    next_frame_ns += frame_ns
    wait_ns = next_frame_ns - time.monotonic_ns()
    if wait_ns > 0:
        time.sleep(wait_ns / 1e9)
    else:
        next_frame_ns = time.monotonic_ns()
