# Touch + buttons demo for the ESP32-S31-Korvo-1 with the 800x480 touch LCD.
# - draw on the canvas with your finger (up to 5 touches, colour per finger)
# - on-screen PLAY plays a chime, VOL-/VOL+ change the speaker volume, SET cycles the brush size
# - BOOT button clears the canvas; the physical ladder buttons show their detected group
# Needs /lib/gt1151.py, /lib/korvo1.py, /lib/adafruit_display_text/.
import time, array
import board, displayio, terminalio, vectorio, neopixel, audiocore
from adafruit_display_text import label
from ulab import numpy as np
import korvo1

RATE = 16000


def chime(volume=9000):
    """Two-tone chime, stereo int16, with 0.35 s of lead-in silence so the codec's wake-up ramp
    never clips the start."""
    n = int(RATE * 0.6)
    t = np.arange(n) / RATE
    env = np.minimum(np.minimum(np.arange(n) / 300, (n - np.arange(n)) / 300), 1.0)
    a = env * (np.sin(2 * np.pi * 523 * t) + np.sin(2 * np.pi * 784 * t)) * 0.5
    b = env * (np.sin(2 * np.pi * 659 * t) + np.sin(2 * np.pi * 988 * t)) * 0.5
    mono = np.concatenate((np.zeros(int(RATE * 0.35)), a, b)) * volume
    stereo = np.zeros(2 * len(mono))
    stereo[0::2] = mono
    stereo[1::2] = mono
    return array.array("h", np.array(stereo, dtype=np.int16))

display = board.DISPLAY
W, H = display.width, display.height
px = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3)

root = displayio.Group()
display.root_group = root


def pal(*colors):
    p = displayio.Palette(len(colors))
    for i, c in enumerate(colors):
        p[i] = c
    return p


def rect(x, y, w, h, color):
    r = vectorio.Rectangle(pixel_shader=pal(color), width=w, height=h, x=x, y=y)
    root.append(r)
    return r


def text(s, x, y, color=0xFFFFFF, scale=2, anchor=(0.5, 0.5)):
    t = label.Label(terminalio.FONT, text=s, color=color, scale=scale)
    t.anchor_point = anchor
    t.anchored_position = (x, y)
    root.append(t)
    return t


rect(0, 0, W, H, 0x0B1220)
# drawing canvas: 2-bit bitmap, 4 colours + transparent background
CANVAS_Y = 60
canvas = displayio.Bitmap(W, H - CANVAS_Y - 90, 8)
cpal = pal(0x000000, 0xFFFFFF, 0xF1C40F, 0x2ECC71, 0x3498DB, 0xE74C3C, 0x9B59B6, 0xE67E22)
cpal.make_transparent(0)
rect(0, CANVAS_Y, W, canvas.height, 0x14213D)
root.append(displayio.TileGrid(canvas, pixel_shader=cpal, x=0, y=CANVAS_Y))

title = text("TOUCH + BUTTONS", W // 2, 24, 0xFFFFFF, 3)
coords = text("touch the screen", W - 12, 24, 0x7F9ACB, 2, (1.0, 0.5))
status = text("", 12, 24, 0x7F9ACB, 2, (0.0, 0.5))

# on-screen buttons along the bottom
BTN_Y, BTN_H = H - 78, 64
names = ("PLAY", "SET", "VOL-", "VOL+")
buttons = []
bw = (W - 5 * 16) // 4
for i, name in enumerate(names):
    x = 16 + i * (bw + 16)
    r = rect(x, BTN_Y, bw, BTN_H, 0x1C2A44)
    text(name, x + bw // 2, BTN_Y + BTN_H // 2, 0xFFFFFF, 3)
    buttons.append((name, x, BTN_Y, bw, BTN_H, r))
last_hit = text("", W // 2, BTN_Y - 18, 0xF1C40F, 2)


def paint(x, y, color, size=4):
    size = brush_sizes[brush] if "brush_sizes" in globals() else size
    for dx in range(-size, size + 1):
        for dy in range(-size, size + 1):
            cx, cy = x + dx, y - CANVAS_Y + dy
            if 0 <= cx < canvas.width and 0 <= cy < canvas.height:
                canvas[cx, cy] = color


def clear():
    canvas.fill(0)


tp = korvo1.touch()              # raw panel coords match the display; flags available if a panel differs
pid, fw = tp.product_id()
boot = korvo1.BootButton()
ladder = korvo1.LadderButtons()
status.text = "GT%s fw %06x" % (pid, fw)
print("touch controller GT%s firmware %06x" % (pid, fw))

codec = korvo1.codec(RATE, 16)
volume_db = -6
spk = korvo1.Speaker(codec, volume_db).__enter__()     # keep the I2S output open for the whole app
sample = audiocore.RawSample(chime(), channel_count=2, sample_rate=RATE)
brush_sizes = (2, 4, 7, 11)
brush = 1
vol_text = text("vol %d dB" % volume_db, W // 2, BTN_Y - 40, 0x7F9ACB, 2)


def on_button(name):
    global volume_db, brush
    if name == "PLAY":
        spk.play(sample)
    elif name == "VOL+" or name == "VOL-":
        volume_db = max(-40, min(6, volume_db + (3 if name == "VOL+" else -3)))
        codec.dac_volume(volume_db)
        vol_text.text = "vol %d dB" % volume_db
        if not spk.out.playing:
            spk.play(sample)                               # audible confirmation of the new level
    elif name == "SET":
        brush = (brush + 1) % len(brush_sizes)
        vol_text.text = "brush %d px" % (brush_sizes[brush] * 2 + 1)

display.auto_refresh = False
display.refresh()
active = None
hit_t = 0
ladder_shown = "x"
while True:
    pts = tp.poll()
    if pts is not None:
        for tid, x, y, strength in pts:
            color = 1 + (tid % 7)
            if y >= CANVAS_Y and y < CANVAS_Y + canvas.height:
                paint(x, y, color)
            for name, bx, by, bwid, bh, r in buttons:
                if bx <= x < bx + bwid and by <= y < by + bh and active != name:
                    active = name
                    hit_t = time.monotonic()
                    r.pixel_shader[0] = 0xF1C40F
                    last_hit.text = "on-screen %s" % name
                    print("on-screen button:", name, "raw", tp.raw, "mapped", (x, y), "rect x %d..%d" % (bx, bx + bwid))
                    px[0] = (255, 160, 0)
                    on_button(name)
        if pts:
            coords.text = "x=%d y=%d  raw %d,%d" % (pts[0][1], pts[0][2], tp.raw[0], tp.raw[1])
        elif active:
            pass
    if active and time.monotonic() - hit_t > 0.25:
        for name, bx, by, bwid, bh, r in buttons:
            r.pixel_shader[0] = 0x1C2A44
        active = None
        px[0] = (0, 0, 0)
    for ev in boot.events():
        print("BOOT", ev)
        if ev == "pressed":
            clear()
            last_hit.text = "BOOT: canvas cleared"
            px[0] = (0, 80, 255)
        else:
            px[0] = (0, 0, 0)
    grp = ladder.read()
    if grp != ladder_shown:
        ladder_shown = grp
        status.text = "ladder: %s" % (grp or "none")
        if grp:
            print("physical button group:", grp)
    display.refresh()
    time.sleep(0.01)
