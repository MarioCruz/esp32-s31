# ESP32-S31-Korvo-1 board helpers: pin map plus speaker/microphone context managers that
# bring up the ES8389 codec in the right order (I2S clocks first, then codec enable).
import time, array
import board, microcontroller as mcu
import audiobusio, audioi2sin
import es8389

I2S_MCLK = mcu.pin.GPIO2      # not used (codec derives its clock from BCLK)
I2S_BCLK = mcu.pin.GPIO3
I2S_LRCLK = mcu.pin.GPIO4
I2S_SDOUT = mcu.pin.GPIO5     # ESP32 -> codec DAC
I2S_SDIN = mcu.pin.GPIO6      # codec ADC -> ESP32 (also latches the codec I2C address at reset)
PA_ENABLE = mcu.pin.GPIO7     # speaker amplifiers, active high
ADC_BUTTONS = mcu.pin.GPIO42  # PLAY / SET / VOL- / VOL+ resistor ladder
SD_POWER = mcu.pin.GPIO39     # microSD power (active low)
LCD_DISP = mcu.pin.GPIO38
CAMERA_XCLK = mcu.pin.GPIO55  # DVP camera: no CircuitPython support on the S31 yet


def codec(sample_rate=16000, bits=16):
    """Open the ES8389 and configure it for the given I2S stream format."""
    c = es8389.ES8389(board.I2C(), pa_pin=PA_ENABLE, addr_pin=I2S_SDIN)
    c.open()
    c.set_fs(sample_rate, bits)
    return c


class Speaker:
    """with korvo1.Speaker(codec, volume_db=-6) as spk: spk.play(sample); spk.wait()"""

    def __init__(self, codec, volume_db=-6):
        self.codec = codec
        self.volume_db = volume_db
        self.out = None

    def __enter__(self):
        self.out = audiobusio.I2SOut(I2S_BCLK, I2S_LRCLK, I2S_SDOUT)
        self.codec.dac_volume(self.volume_db)
        return self

    def play(self, sample, loop=False):
        self.out.play(sample, loop=loop)          # starts the clocks
        self.codec.dac_enable(True)                # then wakes the codec (first time ~0.3 s)

    def wait(self):
        while self.out.playing:
            time.sleep(0.02)

    def stop(self):
        self.out.stop()

    def __exit__(self, *exc):
        self.codec.dac_enable(False)
        self.out.deinit()
        self.out = None


class Microphone:
    """with korvo1.Microphone(codec, gain_db=30) as mic: mic.record(buf, len(buf))
    Mono by default (left mic). stereo=True interleaves left/right."""

    def __init__(self, codec, sample_rate=16000, bit_depth=16, gain_db=30, stereo=False):
        self.codec = codec
        self.sample_rate = sample_rate
        self.bit_depth = bit_depth
        self.gain_db = gain_db
        self.stereo = stereo
        self.mic = None

    def __enter__(self):
        self.mic = audioi2sin.I2SIn(I2S_BCLK, I2S_LRCLK, I2S_SDIN, sample_rate=self.sample_rate,
                                    bit_depth=self.bit_depth, mono=not self.stereo)
        self.codec.mic_gain(self.gain_db)
        self.codec.adc_enable(True)                # waits for the codec state machine
        junk = array.array("h" if self.bit_depth == 16 else "i", [0] * (self.sample_rate // 4))
        self.mic.record(junk, len(junk))           # drop the start-up ramp
        return self

    def record(self, buf, length=None):
        return self.mic.record(buf, len(buf) if length is None else length)

    def __exit__(self, *exc):
        self.codec.adc_enable(False)
        self.mic.deinit()
        self.mic = None
