# Goodix GT1151/GT1158 capacitive touch controller (as on the ESP32-S3-LCD-EV-Board-SUB3 panel).
# I2C address 0x14, 16-bit big-endian register addresses. Report layout per Espressif's
# esp_lcd_touch_gt1151: status byte at 0x814E (bit7 = data ready, bits0-3 = point count), then
# 8-byte records [track_id, x_lo, x_hi, y_lo, y_hi, strength_lo, strength_hi, reserved],
# then a key byte and a checksum byte (whole buffer sums to 0 mod 256).
_STATUS = 0x814E
_PRODUCT_ID = 0x8140


class GT1151:
    def __init__(self, i2c, address=0x14, width=800, height=480, swap_xy=False, flip_x=False, flip_y=False):
        self.i2c = i2c
        self.addr = address
        self.width, self.height = width, height
        self.swap_xy, self.flip_x, self.flip_y = swap_xy, flip_x, flip_y
        self._buf = bytearray(1 + 8 * 5 + 2)
        self.last = []

    def _read(self, reg, buf):
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto_then_readfrom(self.addr, bytes((reg >> 8, reg & 0xFF)), buf)
        finally:
            self.i2c.unlock()

    def _write(self, reg, val):
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto(self.addr, bytes((reg >> 8, reg & 0xFF, val)))
        finally:
            self.i2c.unlock()

    def product_id(self):
        b = bytearray(11)
        self._read(_PRODUCT_ID, b)
        return bytes(b[:4]).decode(), (b[4] << 16) | (b[5] << 8) | b[6]

    def poll(self):
        """Return the current touches as a list of (track_id, x, y, strength).
        Returns None when the controller has no new report since the last poll."""
        st = bytearray(1)
        self._read(_STATUS, st)
        if not st[0] & 0x80:
            return None
        n = st[0] & 0x0F
        if n == 0 or n > 5:
            self._write(_STATUS, 0)
            self.last = []
            return self.last
        length = 1 + 8 * n + 2
        buf = memoryview(self._buf)[:length]
        self._read(_STATUS, buf)
        self._write(_STATUS, 0)
        if sum(buf) & 0xFF:
            return None                                   # checksum error, keep previous state
        pts = []
        for i in range(n):
            o = 1 + 8 * i
            x = buf[o + 1] | (buf[o + 2] << 8)
            y = buf[o + 3] | (buf[o + 4] << 8)
            if self.swap_xy:
                x, y = y, x
            if self.flip_x:
                x = self.width - 1 - x
            if self.flip_y:
                y = self.height - 1 - y
            pts.append((buf[o] & 0x0F, x, y, buf[o + 5] | (buf[o + 6] << 8)))
        self.last = pts
        return pts

    @property
    def touched(self):
        return bool(self.last)
