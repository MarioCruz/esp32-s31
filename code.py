# SPDX-FileCopyrightText: 2026 Tim Cocks for Adafruit Industries (original Metro RP2350 demo)
# SPDX-License-Identifier: MIT
"""PixelDust digital sand on the ESP32-S31-Korvo-1's 800x480 display.

Port of Adafruit's "PixelDust digital sand for CircuitPython" (Metro RP2350 version):
  https://learn.adafruit.com/pixeldust-digital-sand-for-circuitpython
Physics are the unmodified viper kernels in lib/sand_viper.mpy, compiled for this chip with
  mpy-cross -march=rv32imc sand/sand_viper.py -o lib/sand_viper.mpy
Differences from the original: the picogame Scene/Canvas is replaced by a displayio Bitmap the
kernels write into directly, and the accelerometer (this board has none) is replaced by the touch
screen: touch anywhere and the sand falls toward your finger. With no finger, gravity slowly
rotates. BOOT re-scatters the sand.
"""
import gc, math, random, time
import board, displayio
import sand_viper
import logo
import korvo1

SCALE = 4                  # pixels per grain; 800x480 at 4 -> 200x120 cells
FILL = 0.15                # fraction of cells holding a grain
STRIPES = 6                # rainbow bands at start; 0 = scattered colours
MAX_SPEED = 5              # cells per frame
MAX_FPS = 45               # simulation steps per second
REFRESH_EVERY = 1          # set to 2 if the picture ever rolls (halves the PSRAM traffic from refreshes)
BACKGROUND_RGB = (0, 0, 0)
LOGO_RGB = (255, 255, 255)
LOGO_SCALE = 3             # logo cells per logo pixel (40x40 logo -> 120x120 cells)


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


BACKGROUND_COLOR = rgb565(*BACKGROUND_RGB)
display = board.DISPLAY
screen_width, screen_height = display.width, display.height
GRID_WIDTH, GRID_HEIGHT = screen_width // SCALE, screen_height // SCALE
GRAIN_COUNT = int(GRID_WIDTH * GRID_HEIGHT * FILL)

# -- display: one RGB565 bitmap the kernels write straight into --------------------------
gc.collect()
# Full-resolution RGB565 bitmap (768 KB in PSRAM) that the kernels paint SCALE x SCALE pixels per cell
# into. A 1-px-per-cell bitmap scaled by displayio was tried: 10x slower refresh (270 ms).
# The dot-clock panel streams its framebuffer from PSRAM and loses sync (the picture rolls) when
# other PSRAM traffic gets heavy, so the screen is refreshed only every REFRESH_EVERY steps.
bitmap = displayio.Bitmap(GRID_WIDTH * SCALE, GRID_HEIGHT * SCALE, 65536)
root = displayio.Group()
root.append(displayio.TileGrid(bitmap, pixel_shader=displayio.ColorConverter(input_colorspace=displayio.Colorspace.RGB565),
                               x=(screen_width - GRID_WIDTH * SCALE) // 2, y=(screen_height - GRID_HEIGHT * SCALE) // 2))
display.root_group = root
CELL_PX = SCALE
display.auto_refresh = False

# -- sand state: same layout as sand_viper.new(), but `pixels` is the bitmap ----------------
import array
logo_w, logo_h = logo.WIDTH * LOGO_SCALE, logo.HEIGHT * LOGO_SCALE
grid = bytearray(GRID_WIDTH * GRID_HEIGHT)
grains = array.array("i", [0]) * (5 * GRAIN_COUNT)
params = array.array("i", [0]) * (sand_viper.PARAM_BACKDROP_COLORS + logo_w * logo_h)
params[sand_viper.PARAM_GRID_WIDTH] = GRID_WIDTH
params[sand_viper.PARAM_GRID_HEIGHT] = GRID_HEIGHT
params[sand_viper.PARAM_GRAIN_COUNT] = GRAIN_COUNT
params[sand_viper.PARAM_CELL_SIZE] = CELL_PX
params[sand_viper.PARAM_BACKGROUND] = BACKGROUND_COLOR
params[sand_viper.PARAM_RANDOM_STATE] = random.getrandbits(30)
params[sand_viper.PARAM_JITTER_RANGE] = 1
params[sand_viper.PARAM_MAX_SPEED] = int(MAX_SPEED * 256)
pixels = bitmap


def blend(coverage):
    w = coverage + 1
    return rgb565(*(((lc * w + bc * (257 - w)) >> 8) for lc, bc in zip(LOGO_RGB, BACKGROUND_RGB)))


# Scale the 40x40 logo up by LOGO_SCALE cells per logo pixel.
mask_row_bytes = (logo.WIDTH + 7) // 8
colors = []
solid = bytearray(logo_w * logo_h)
shades = [blend(c) for c in range(256)]
for y in range(logo_h):
    ly = y // LOGO_SCALE
    for x in range(logo_w):
        lx = x // LOGO_SCALE
        colors.append(shades[logo.GRAY[ly * logo.WIDTH + lx]])
        solid[y * logo_w + x] = 1 if logo.MASK[ly * mask_row_bytes + lx // 8] & (0x80 >> (lx & 7)) else 0
sand_viper.backdrop(grid, params, (GRID_WIDTH - logo_w) // 2, (GRID_HEIGHT - logo_h) // 2, logo_w, logo_h, colors, solid)
del colors, solid, shades


def rainbow(hue):
    s = hue * 6
    sector = int(s)
    rising = int((s - sector) * 255)
    falling = 255 - rising
    r, g, b = ((255, rising, 0), (falling, 255, 0), (0, 255, rising), (0, falling, 255), (rising, 0, 255), (255, 0, falling))[sector % 6]
    return rgb565(r, g, b)


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
    bitmap.dirty()
    display.refresh()


scatter()

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
        mag = min(1.0, math.sqrt(fx * fx + fy * fy) * 1.5)
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
poll_every = 3
n = 0
while True:
    n += 1
    if n % poll_every == 0:                       # touch poll is ~1 ms of I2C; not every frame
        pts = touch.poll()
        if pts is not None:
            finger = (pts[0][1], pts[0][2]) if pts else None
    for ev in boot.events():
        if ev == "pressed":
            scatter()
    accel_x, accel_y, jitter_range = read_acceleration()
    params[sand_viper.PARAM_ACCEL_X] = accel_x
    params[sand_viper.PARAM_ACCEL_Y] = accel_y
    params[sand_viper.PARAM_JITTER_RANGE] = jitter_range

    t0 = time.monotonic_ns()
    if sand_viper.step(grains, grid, pixels, params):
        bitmap.dirty(params[sand_viper.PARAM_DIRTY_LEFT] * SCALE, params[sand_viper.PARAM_DIRTY_TOP] * SCALE,
                     params[sand_viper.PARAM_DIRTY_RIGHT] * SCALE, params[sand_viper.PARAM_DIRTY_BOTTOM] * SCALE)
    t1 = time.monotonic_ns()
    if n % REFRESH_EVERY == 0:
        display.refresh()
    t2 = time.monotonic_ns()
    frames += 1; step_ns += t1 - t0; draw_ns += t2 - t1
    if t2 >= report_ns:
        print("%d fps, step %d us, draw %d us, gravity (%d, %d)%s" % (frames // 2, step_ns // frames // 1000, draw_ns // frames // 1000,
                                                                       accel_x, accel_y, " finger" if finger else ""))
        frames = step_ns = draw_ns = 0
        report_ns += 2000000000
    next_frame_ns += frame_ns
    wait_ns = next_frame_ns - time.monotonic_ns()
    if wait_ns > 0:
        time.sleep(wait_ns / 1e9)
    else:
        next_frame_ns = time.monotonic_ns()
