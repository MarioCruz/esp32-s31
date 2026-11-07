# Speaker + microphone test for the ESP32-S31-Korvo-1.
# 1) two-tone chime on the speakers  2) 3 s stereo recording with a level trace  3) playback.
# Needs /lib/es8389.py and /lib/korvo1.py.  Run: ./run.py audio_test.py   (or push as code.py)
import array, math, time
import audiocore
import korvo1

RATE = 16000
codec = korvo1.codec(RATE, 16)
print("ES8389 at 0x%02x, id %02x%02x" % ((codec.addr,) + codec.chip_id()))


def tone(freq_a, freq_b, seconds, amp=9000):
    n = int(RATE * seconds)
    buf = array.array("h", [0] * (2 * n))
    for i in range(n):
        env = min(1.0, i / 300, (n - i) / 300)
        v = int(amp * env * 0.5 * (math.sin(2 * math.pi * freq_a * i / RATE)
                                   + math.sin(2 * math.pi * freq_b * i / RATE)))
        buf[2 * i] = v
        buf[2 * i + 1] = v
    return buf


def level_trace(buf, channels, block=0.2):
    step = int(RATE * block) * channels
    out = []
    for i in range(0, len(buf) - step + 1, step):
        acc = 0
        for j in range(i, i + step):
            acc += buf[j] * buf[j]
        out.append(int(math.sqrt(acc / step)))
    return out


chime = array.array("h", tone(523, 784, 0.6) + tone(659, 988, 0.6))
with korvo1.Speaker(codec, volume_db=-6) as spk:
    print("speaker: chime x2")
    spk.play(audiocore.RawSample(chime, channel_count=2, sample_rate=RATE), loop=True)
    time.sleep(2.6)
    spk.stop()

print("mic: recording 3 s stereo ... talk or clap")
rec = array.array("h", [0] * (RATE * 3 * 2))
with korvo1.Microphone(codec, RATE, gain_db=30, stereo=True) as mic:
    got = mic.record(rec)
left = array.array("h", [0] * (len(rec) // 2)); right = array.array("h", [0] * (len(rec) // 2))
for i in range(len(left)):
    left[i] = rec[2 * i]; right[i] = rec[2 * i + 1]
print("mic: got %d frames; L peak %d  R peak %d" % (got, max(abs(x) for x in left), max(abs(x) for x in right)))
print("mic: level trace (rms per 200 ms)  L:", level_trace(left, 1))
print("                                   R:", level_trace(right, 1))

with korvo1.Speaker(codec, volume_db=0) as spk:
    print("speaker: playing the recording back")
    spk.play(audiocore.RawSample(rec, channel_count=2, sample_rate=RATE))
    spk.wait()
print("done")
