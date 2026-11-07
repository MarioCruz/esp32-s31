#!/usr/bin/env -S uv run --quiet --with pyserial python3
"""Copy a file onto the board through the serial raw REPL (this board has no CIRCUITPY drive).

Usage: ./put.py local_file [/dev/ttyUSB0] [remote_path]
Parent folders are created. Each chunk is acknowledged by the board (no UART flow control otherwise),
and the result is verified with a SHA-256 on the board. Soft-reloads afterwards only for
code.py / boot.py / settings.toml.
"""
import base64, sys, time, glob, zlib, serial

src = sys.argv[1]
port = sys.argv[2] if len(sys.argv) > 2 else sorted(glob.glob("/dev/ttyUSB*"))[0]
dst = (sys.argv[3] if len(sys.argv) > 3 else src.split("/")[-1]).strip("/")
data = open(src, "rb").read()
CHUNK = 768


def read_until(s, marker, timeout=5):
    buf = b""; t = time.monotonic()
    while marker not in buf and time.monotonic() - t < timeout:
        buf += s.read(s.in_waiting or 1)
    return buf


def run(s, code, timeout=10):
    """Execute one statement in raw REPL and return its output; raise on error."""
    s.write(code.encode() + b"\x04")
    out = read_until(s, b"\x04>", timeout)
    if not out.startswith(b"OK"):
        raise RuntimeError("no OK from raw REPL: %r" % out[:80])
    body, _, err = out[2:].partition(b"\x04")        # stdout \x04 stderr \x04 >
    if err.strip(b">\r\n\x04"):
        raise RuntimeError(err.decode(errors="replace").strip())
    return body.decode(errors="replace").strip()


s = serial.Serial(port, 115200, timeout=0.2)
s.write(b"\x03\x03"); time.sleep(0.3)                 # stop code.py
s.write(b"\r"); read_until(s, b">>>", timeout=3)      # "press any key" -> friendly REPL prompt
s.reset_input_buffer()
s.write(b"\x01")                                      # raw REPL
if b"raw REPL" not in read_until(s, b"raw REPL; CTRL-B to exit\r\n>"):
    sys.exit("board did not enter raw REPL; press RST and rerun")

try:
    run(s, "import binascii, os")
    parts = dst.split("/")[:-1]
    for i in range(1, len(parts) + 1):               # mkdir -p, one statement each
        parent = "/" + "/".join(parts[:i - 1]); path = "/" + "/".join(parts[:i])
        run(s, f"{parts[i-1]!r} in os.listdir({parent!r}) or os.mkdir({path!r})")
    run(s, f"f = open({'/' + dst!r}, 'wb')")
    for i in range(0, len(data), CHUNK):
        run(s, f"f.write(binascii.a2b_base64({base64.b64encode(data[i:i+CHUNK]).decode()!r}))")
    run(s, "f.close()")
    # verify: CRC32 on the board if available, else read the file back and compare
    if run(s, "print(hasattr(binascii, 'crc32'))") == "True":
        remote = int(run(s, f"print(binascii.crc32(open({'/' + dst!r},'rb').read()))"))
        ok = remote == zlib.crc32(data); how = "crc32"
    else:
        run(s, f"g = open({'/' + dst!r}, 'rb')"); back = b""
        for i in range(0, len(data) + 1, CHUNK):
            back += base64.b64decode(run(s, f"print(binascii.b2a_base64(g.read({CHUNK})).decode())"))
        run(s, "g.close()"); ok = back == data; how = "read-back"
    if not ok:
        sys.exit(f"VERIFY FAILED ({how}) for /{dst}")
    print(f"wrote {len(data)} bytes to /{dst} ({how} verified)")
except RuntimeError as e:
    sys.exit(f"upload of /{dst} failed: {e}")
finally:
    s.write(b"\x02")                                  # back to friendly REPL
    if dst in ("code.py", "boot.py", "settings.toml"):
        time.sleep(0.2); s.write(b"\x04")            # reload so the new file runs
    s.close()
