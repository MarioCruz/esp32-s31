# Minimal first test, no libraries needed. Push with: ./put.py blink.py /dev/ttyUSB0 code.py
import time, board, digitalio, neopixel_write
pin = digitalio.DigitalInOut(board.NEOPIXEL)
pin.direction = digitalio.Direction.OUTPUT
# WS2812 byte order is GRB
for color in ((0, 40, 0), (40, 0, 0), (0, 0, 40), (0, 0, 0)) * 1000:
    neopixel_write.neopixel_write(pin, bytearray(color))
    print("led", color)
    time.sleep(0.4)
