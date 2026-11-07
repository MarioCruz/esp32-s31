# Live stereo microphone level meter on the Korvo-1's 800x480 display.
# Needs /lib/es8389.py, /lib/korvo1.py, /lib/adafruit_display_text/.
import array, math, time
import board, displayio, terminalio, vectorio, neopixel
from adafruit_display_text import label
import korvo1

try:
    from ulab import numpy as np
except ImportError:
    np = None

RATE = 16000
CHUNK = RATE // 20                     # 50 ms per update
MIN_DB, MAX_DB = -60, 0
display = board.DISPLAY
W, H = display.width, display.height
px = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3)

# ---------- layout ----------
root = displayio.Group()
display.root_group = root


def pal(color):
    p = displayio.Palette(1); p[0] = color; return p


def rect(x, y, w, h, color):
    r = vectorio.Rectangle(pixel_shader=pal(color), width=max(1, w), height=max(1, h), x=x, y=y)
    root.append(r); return r


def text(s, x, y, color=0xFFFFFF, scale=2, anchor=(0, 0.5)):
    t = label.Label(terminalio.FONT, text=s, color=color, scale=scale)
    t.anchor_point = anchor; t.anchored_position = (x, y)
    root.append(t); return t


rect(0, 0, W, H, 0x0B1220)                                   # background
text("MIC LEVEL", W // 2, 36, 0xFFFFFF, 4, (0.5, 0.5))
text("ESP32-S31-Korvo-1  /  ES8389  /  16 kHz", W // 2, 76, 0x7F9ACB, 2, (0.5, 0.5))

TOP, BOTTOM = 120, H - 70
SPAN = BOTTOM - TOP
BAR_W = 150
GREEN, YELLOW, RED = 0x2ECC71, 0xF1C40F, 0xE74C3C
LEVEL_Y = -20, -6                                            # yellow starts at -20 dB, red at -6 dB


def db_to_y(db):
    db = max(MIN_DB, min(MAX_DB, db))
    return int(BOTTOM - (db - MIN_DB) / (MAX_DB - MIN_DB) * SPAN)


# dB scale between the bars
for db in range(MIN_DB, MAX_DB + 1, 10):
    y = db_to_y(db)
    rect(W // 2 - 60, y, 120, 1, 0x2A3A55)
    text("%d" % db, W // 2, y, 0x7F9ACB, 2, (0.5, 0.5))

channels = []
for name, cx in (("LEFT", W // 2 - 220), ("RIGHT", W // 2 + 220)):
    x = cx - BAR_W // 2
    rect(x - 4, TOP - 4, BAR_W + 8, SPAN + 8, 0x1C2A44)       # well
    segs = {
        "g": rect(x, BOTTOM, BAR_W, 1, GREEN),
        "y": rect(x, BOTTOM, BAR_W, 1, YELLOW),
        "r": rect(x, BOTTOM, BAR_W, 1, RED),
    }
    peak = rect(x, BOTTOM, BAR_W, 3, 0xFFFFFF)
    text(name, cx, TOP - 24, 0xFFFFFF, 2, (0.5, 0.5))
    readout = text("-inf dB", cx, BOTTOM + 36, 0xFFFFFF, 3, (0.5, 0.5))
    channels.append({"segs": segs, "peak": peak, "readout": readout, "peak_db": MIN_DB, "peak_t": 0, "shown": -99})


def set_bar(ch, db):
    y_top = db_to_y(db)
    y_yel, y_red = db_to_y(LEVEL_Y[0]), db_to_y(LEVEL_Y[1])
    # green: from bottom up to min(top, yellow threshold); yellow: between thresholds; red: above
    g_top = max(y_top, y_yel); yl_top = max(y_top, y_red)
    segs = ch["segs"]
    segs["g"].y = g_top;  segs["g"].height = max(1, BOTTOM - g_top)
    segs["y"].y = yl_top; segs["y"].height = max(1, y_yel - yl_top) if y_top < y_yel else 1
    segs["r"].y = y_top;  segs["r"].height = max(1, y_red - y_top) if y_top < y_red else 1
    if y_top >= y_yel:
        segs["y"].y = BOTTOM; segs["r"].y = BOTTOM
    elif y_top >= y_red:
        segs["r"].y = BOTTOM


def to_db(rms):
    return 20 * math.log(rms / 32768, 10) if rms > 1 else MIN_DB


def levels(buf):
    """(rms_L, rms_R, peak_L, peak_R) from interleaved int16."""
    if np is not None:
        a = np.frombuffer(buf, dtype=np.int16)
        l = np.array(a[0::2], dtype=np.float); r = np.array(a[1::2], dtype=np.float)
        return (math.sqrt(np.mean(l * l)), math.sqrt(np.mean(r * r)),
                float(np.max(abs(l))), float(np.max(abs(r))))
    acc = [0, 0]; pk = [0, 0]
    for i in range(0, len(buf), 2):
        for c in (0, 1):
            v = buf[i + c]; acc[c] += v * v
            if v < 0: v = -v
            if v > pk[c]: pk[c] = v
    n = len(buf) // 2
    return math.sqrt(acc[0] / n), math.sqrt(acc[1] / n), pk[0], pk[1]


status = text("starting codec...", W // 2, H - 18, 0x7F9ACB, 2, (0.5, 0.5))
codec = korvo1.codec(RATE, 16)
buf = array.array("h", [0] * (CHUNK * 2))
display.auto_refresh = False
display.refresh()

with korvo1.Microphone(codec, RATE, gain_db=30, stereo=True) as mic:
    status.text = "gain 30 dB   |   bars = RMS, white line = peak hold"
    frames = 0
    t_fps = time.monotonic()
    while True:
        mic.record(buf)
        rms_l, rms_r, pk_l, pk_r = levels(buf)
        now = time.monotonic()
        for ch, rms, pk in ((channels[0], rms_l, pk_l), (channels[1], rms_r, pk_r)):
            db = to_db(rms)
            set_bar(ch, db)
            pdb = to_db(pk)
            if pdb >= ch["peak_db"] or now - ch["peak_t"] > 1.5:
                ch["peak_db"] = pdb; ch["peak_t"] = now
            else:
                ch["peak_db"] -= 0.8                           # slow fall after hold
            ch["peak"].y = db_to_y(ch["peak_db"]) - 1
            if abs(db - ch["shown"]) >= 0.5:
                ch["readout"].text = "%5.1f dB" % db if db > MIN_DB else " -inf dB"
                ch["shown"] = db
        loud = max(to_db(rms_l), to_db(rms_r))
        px[0] = RED if loud > LEVEL_Y[1] else YELLOW if loud > LEVEL_Y[0] else GREEN
        display.refresh()
        frames += 1
        if frames % 40 == 0:
            print("L %5.1f dB  R %5.1f dB  (%.1f updates/s)" % (to_db(rms_l), to_db(rms_r), 40 / (now - t_fps)))
            t_fps = now
