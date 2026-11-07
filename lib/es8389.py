# Minimal CircuitPython driver for the Everest ES8389 audio codec, as wired on the
# ESP32-S31-Korvo-1: I2C control, I2S slave, no MCLK (internal clock derived from BCLK),
# differential MIC1/MIC2 inputs, power-amplifier enable on a GPIO.
# Register sequences ported from Espressif's esp_codec_dev es8389.c (Apache-2.0).
import time
import digitalio

# (ratio, bclk_hz, rate): reg 04,05,06,07,08,09,0A,0F,11,21,22,26,30,41,42,43,F0,F1,16,18,19
_COEFF = {
    (32, 256000, 8000):   (0x00,0x57,0x84,0xD0,0x03,0xC1,0xB0,0x00,0x00,0x1F,0x7F,0xBF,0xC0,0xFF,0x7F,0x01,0x12,0x00,0x09,0x19,0x07),
    (64, 512000, 8000):   (0x00,0x4D,0x24,0xC0,0x03,0xD1,0xB0,0x00,0x00,0x1F,0x7F,0xBF,0xC0,0xFF,0x7F,0x01,0x12,0x00,0x09,0x19,0x07),
    (32, 512000, 16000):  (0x00,0x55,0x84,0xD0,0x01,0xC1,0x90,0x00,0x00,0x1F,0x7F,0xBF,0xC0,0xFF,0x7F,0x00,0x12,0x00,0x12,0x31,0x0E),
    (64, 1024000, 16000): (0x00,0x45,0x24,0xC0,0x01,0xD1,0x90,0x00,0x00,0x1F,0x7F,0xBF,0xC0,0xFF,0x7F,0x00,0x12,0x00,0x12,0x31,0x0E),
    (32, 1411200, 44100): (0x00,0x45,0xA4,0xD0,0x10,0xD1,0x80,0x00,0x00,0x1F,0x7F,0xBF,0xC0,0x7F,0x7F,0x00,0x12,0x00,0x35,0x91,0x28),
    (64, 2822400, 44100): (0x00,0x51,0x00,0xC0,0x10,0xC1,0x80,0x00,0x00,0x1F,0x7F,0xBF,0xC0,0x7F,0x7F,0x00,0x12,0x00,0x35,0x91,0x28),
    (32, 1536000, 48000): (0x00,0x45,0xA4,0xD0,0x10,0xD1,0x80,0x00,0x00,0x1F,0x7F,0xBF,0xC0,0x7F,0x7F,0x00,0x12,0x00,0x35,0x91,0x28),
    (64, 3072000, 48000): (0x00,0x51,0x04,0xC0,0x10,0xC1,0x80,0x00,0x00,0x1F,0x7F,0xBF,0xC0,0x7F,0x7F,0x00,0x12,0x00,0x35,0x91,0x28),
    (64, 6144000, 96000): (0x00,0x41,0x00,0xD0,0x10,0xD1,0x80,0x00,0x00,0x9F,0x7F,0xBF,0xC0,0x7F,0x7F,0x80,0x12,0xC0,0x35,0x91,0x28),
}
_BITS = {16: 3 << 5, 24: 0, 32: 4 << 5}
_INSEL_L = 1   # differential MIC1P/MIC1N (left on-board mic)
_INSEL_R = 1   # differential MIC2N/MIC2P (right on-board mic)
_MIC_GAIN_STEPS = ((3, 0), (6, 1), (9, 2), (12, 3), (15, 6), (18, 7), (21, 8), (24, 9),
                   (27, 10), (30, 11), (33, 12), (36, 13))


class ES8389:
    def __init__(self, i2c, address=0x10, pa_pin=None, addr_pin=None):
        """addr_pin: the codec's DSIN/ADC-data pin (GPIO6 on the Korvo-1). The ES8389 latches its
        I2C address from that pin at reset: low -> 0x10, high/floating -> 0x12. It is held low
        during open() so the address is predictable, then released for I2S use."""
        self.i2c = i2c
        self.addr = address
        self.addr_pin = addr_pin
        self._buf = bytearray(1)
        self.pa = None
        if pa_pin is not None:
            self.pa = digitalio.DigitalInOut(pa_pin)
            self.pa.switch_to_output(value=False)

    # --- register access -------------------------------------------------
    def _xfer(self, out, inbuf=None):
        for attempt in (0, 1):
            while not self.i2c.try_lock():
                pass
            try:
                if inbuf is None:
                    self.i2c.writeto(self.addr, out)
                else:
                    self.i2c.writeto_then_readfrom(self.addr, out, inbuf)
                return
            except OSError:
                if attempt:
                    raise
                self.addr = self._find()        # address may have been re-latched; retry once
            finally:
                self.i2c.unlock()

    def _w(self, reg, val):
        self._xfer(bytes((reg, val & 0xFF)))

    def _r(self, reg):
        self._xfer(bytes((reg,)), self._buf)
        return self._buf[0]

    def _upd(self, reg, mask, val):
        self._w(reg, (self._r(reg) & ~mask) | (val & mask))

    def chip_id(self):
        return self._r(0xFD), self._r(0xFE)

    # --- bring-up ---------------------------------------------------------
    def _find(self):
        while not self.i2c.try_lock():
            pass
        try:
            found = [a for a in self.i2c.scan() if 0x10 <= a <= 0x13]
        finally:
            self.i2c.unlock()
        if not found:
            raise OSError("ES8389 not found on I2C (looked at 0x10-0x13)")
        return found[0]

    def open(self):
        w = self._w
        pin = None
        if self.addr_pin is not None:
            pin = digitalio.DigitalInOut(self.addr_pin)
            pin.switch_to_output(value=False)
            time.sleep(0.002)
        try:
            self.addr = self._find()
            w(0xF3, 0x00)
            w(0x00, 0x7E)                      # reset: address pin is re-latched here
            time.sleep(0.01)
            self.addr = self._find()
            self._open_regs()
            self._bias_on()
            self._upd(0x01, 0x01, 0x00)      # I2S slave (ESP32 drives BCLK/LRCLK)
            self._upd(0x02, 0xC0, 0x40)      # internal MCLK derived from BCLK pin
            w(0xF0, 0x12)
        finally:
            if pin:
                pin.deinit()
        self.addr = self._find()             # settle on whatever address it ended up with

    def _open_regs(self):
        w = self._w
        for reg, val in (
            (0xF3, 0x38), (0x24, 0x64), (0x25, 0x04), (0x45, 0x03),
            (0x60, 0x2A), (0x61, 0xC9), (0x62, 0x4F), (0x63, 0x06), (0x6B, 0x00), (0x6D, 0x16),
            (0x6E, 0xAA), (0x6F, 0x66), (0x70, 0x99), (0x23, 0x00),
            (0x72, _INSEL_L << 4), (0x73, _INSEL_R << 4),
            (0x10, 0xC4), (0x01, 0x08), (0xF1, 0x00),
            (0x12, 0x01), (0x13, 0x01), (0x14, 0x01), (0x15, 0x01), (0x16, 0x35), (0x17, 0x09),
            (0x18, 0x91), (0x19, 0x28), (0x1A, 0x01), (0x1B, 0x01), (0x1C, 0x11),
            (0x2A, 0x00), (0x20, 0x60), (0x40, 0x60),          # 16-bit, I2S, unmuted
            (0xF0, 0x01), (0x02, 0x00), (0x04, 0x00), (0x05, 0x10), (0x06, 0x00), (0x07, 0xC0),
            (0x08, 0x00), (0x09, 0xC0), (0x0A, 0x80), (0x0B, 0x04), (0x0C, 0x01), (0x0D, 0x00),
            (0x0F, 0x10), (0x21, 0x1F), (0x22, 0x7F), (0x2F, 0xC0), (0x30, 0xF4), (0x31, 0x00),
            (0x44, 0x00), (0x41, 0x7F), (0x42, 0x7F), (0x43, 0x10), (0x49, 0x0F), (0x4C, 0xC0),
            (0x00, 0x00), (0x03, 0xC1), (0x00, 0x01), (0x4D, 0x00),
            (0x26, 191), (0x27, 191), (0x28, 191),             # ADC digital volume 0 dB
            (0x46, 191), (0x47, 191), (0x48, 95 << 1),         # DAC digital volume 0 dB
        ):
            w(reg, val)

    def _bias_on(self):
        self._w(0x4D, 0x00)
        self._upd(0x69, 0x20, 0x20)
        for reg, val in ((0x61, 0xD9), (0x64, 0x8F), (0x10, 0xE4), (0x00, 0x01),
                         (0x03, 0xC3), (0x24, 0x6A), (0x25, 0x0A)):
            self._w(reg, val)

    def set_fs(self, sample_rate, bits=16, slot_bits=None):
        """Configure clocks for the I2S stream CircuitPython will produce.
        CircuitPython uses slots as wide as the sample (16-bit -> BCLK = 32 x fs)."""
        slot_bits = slot_bits or bits
        bclk = sample_rate * slot_bits * 2
        key = (slot_bits * 2, bclk, sample_rate)
        if key not in _COEFF:
            raise ValueError("unsupported rate/bits %r; supported: %r" % (key, sorted(_COEFF)))
        c = _COEFF[key]
        w, u = self._w, self._upd
        w(0x04, c[0]); w(0x05, c[1]); w(0x06, c[2]); w(0x07, c[3]); w(0x08, c[4]); w(0x09, c[5]); w(0x0A, c[6])
        u(0x0F, 0xC0, c[7]); w(0x11, c[8]); w(0x21, c[9]); w(0x22, c[10]); w(0x26, c[11])
        u(0x30, 0xC0, c[12]); w(0x41, c[13]); w(0x42, c[14]); u(0x43, 0x81, c[15]); u(0xF0, 0x73, c[16])
        w(0xF1, c[17]); w(0x16, c[18]); w(0x18, c[19]); w(0x19, c[20])
        code = _BITS[bits]
        u(0x20, 0xE0, code); u(0x40, 0xE0, code)      # data length
        u(0x0C, 0xE0, 0x00); u(0x20, 0x1C, 0x00); u(0x40, 0x1C, 0x00)   # standard I2S format
        self._bias_on()

    # --- playback -----------------------------------------------------------
    def dac_volume(self, db):
        """Digital DAC volume, -95.5 .. +32 dB (0 dB = full-scale passthrough)."""
        reg = max(0, min(255, int(round((db + 95.5) * 2))))
        self._w(0x46, reg); self._w(0x47, reg)

    # The ES8389's clock state machine (reg 0xF1) only reaches ON (0x0D) once BCLK/LRCLK are
    # running, so start the I2S object *before* calling dac_enable()/adc_enable().
    STATE_ON = 0x0D

    def ready(self):
        return self._r(0xF1) == self.STATE_ON

    def wait_ready(self, timeout=2.0):
        t = time.monotonic()
        while not self.ready():
            if time.monotonic() - t > timeout:
                raise RuntimeError("ES8389 did not start: are the I2S clocks running?")
            time.sleep(0.005)

    def dac_enable(self, enable=True, wait=True):
        if enable:
            if not self.ready():
                self._bias_on()
                if wait:
                    self.wait_ready()
                self._w(0x4D, 0x00)
                time.sleep(0.07)
            if self.pa:
                self.pa.value = True
            self._upd(0x40, 0x03, 0x00)          # unmute
        else:
            self._upd(0x40, 0x03, 0x03)          # mute
            if self.pa:
                self.pa.value = False
            self._upd(0x61, 0x20, 0x00)
            self._w(0x10, 0xD4)

    # --- capture ------------------------------------------------------------
    def mic_gain(self, db):
        """Analog mic PGA gain, 0 .. 36.5 dB in ~3 dB steps, both channels."""
        code = 14
        for limit, c in _MIC_GAIN_STEPS:
            if db < limit:
                code = c
                break
        self._w(0x72, (_INSEL_L << 4) | code)
        self._w(0x73, (_INSEL_R << 4) | code)

    def adc_enable(self, enable=True, wait=True):
        if enable:
            if not self.ready():
                self._bias_on()
                if wait:
                    self.wait_ready()
            self._upd(0x20, 0x03, 0x00)          # unmute
        else:
            self._upd(0x20, 0x03, 0x03)
            self._w(0x64, 0x00)

    # --- shutdown -----------------------------------------------------------
    def close(self):
        self._upd(0x20, 0x03, 0x03); self._upd(0x40, 0x03, 0x03)
        if self.pa:
            self.pa.value = False
        self._w(0x10, 0xD4); time.sleep(0.07)
        for reg, val in ((0x61, 0x59), (0x64, 0x00), (0x03, 0x00), (0x00, 0x7E)):
            self._w(reg, val)
        self._upd(0x40, 0x03, 0x00)
        for reg, val in ((0x01, 0x28), (0x60, 0x00), (0x00, 0x00), (0x10, 0xCC)):
            self._w(reg, val)
        self._upd(0x69, 0x20, 0x00)
        time.sleep(0.5)
        for reg, val in ((0x10, 0x00), (0x61, 0x08), (0xF3, 0xC1), (0xF2, 0x00)):
            self._w(reg, val)
