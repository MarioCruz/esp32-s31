#!/usr/bin/env -S uv run --quiet --with pyserial python3
"""Run a local Python script on the board without touching code.py, streaming its output.

Usage: ./run.py script.py [/dev/ttyUSB0] [timeout_seconds]
"""
import base64, sys, time, glob, serial

src = sys.argv[1]
port = sys.argv[2] if len(sys.argv) > 2 else sorted(glob.glob("/dev/ttyUSB*"))[0]
timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 60
data = open(src, "rb").read()
CHUNK = 768


def read_until(s, marker, timeout=5):
    buf = b""; t = time.monotonic()
    while marker not in buf and time.monotonic() - t < timeout:
        buf += s.read(s.in_waiting or 1)
    return buf


def run(s, code, timeout=10):
    s.write(code.encode() + b"\x04")
    out = read_until(s, b"\x04>", timeout)
    if not out.startswith(b"OK"):
        raise RuntimeError("no OK from raw REPL: %r" % out[:80])
    body, _, err = out[2:].partition(b"\x04")
    if err.strip(b">\r\n\x04"):
        raise RuntimeError(err.decode(errors="replace").strip())
    return body.decode(errors="replace")


s = serial.Serial(port, 115200, timeout=0.2)
s.write(b"\x03\x03"); time.sleep(0.3)
s.write(b"\r"); read_until(s, b">>>", timeout=3)
s.reset_input_buffer()
s.write(b"\x01")
if b"raw REPL" not in read_until(s, b"raw REPL; CTRL-B to exit\r\n>"):
    sys.exit("board did not enter raw REPL; press RST and rerun")
run(s, "import binascii; f = open('/_run.py', 'wb')")
for i in range(0, len(data), CHUNK):
    run(s, f"f.write(binascii.a2b_base64({base64.b64encode(data[i:i+CHUNK]).decode()!r}))")
run(s, "f.close()")
# execute, streaming output until the raw REPL end marker
s.write(b"exec(open('/_run.py').read())\x04")
read_until(s, b"OK", 3)
t = time.monotonic(); buf = b""
while time.monotonic() - t < timeout:
    chunk = s.read(s.in_waiting or 1)
    if chunk:
        buf += chunk
        sys.stdout.write(chunk.decode(errors="replace").replace("\x04", "")); sys.stdout.flush()
        if buf.endswith(b"\x04>") or buf.endswith(b"\x04\x04>"):
            break
else:
    print("\n[run.py: timeout, interrupting]"); s.write(b"\x03")
s.write(b"\x02"); s.close()
print()
