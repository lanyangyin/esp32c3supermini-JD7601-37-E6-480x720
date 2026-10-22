# jd7601.py — 纯 JD7601 驱动（SoftSPI，不占用硬件 SPI host）
from machine import Pin, SoftSPI
import time


class JD7601:
    def __init__(self, sck=4, mosi=6, cs=3, dc=9, rst=8, busy=2, miso=0):
        # SoftSPI 强制要求 sck/mosi/miso 齐全；
        # EPD 只写不读，miso 用 GPIO 0 占位（C3 上 GPIO 0 非 strapping pin）
        self.spi = SoftSPI(
            baudrate=1_000_000,
            polarity=0,
            phase=0,
            sck=Pin(sck),
            mosi=Pin(mosi),
            miso=Pin(miso)
        )
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.dc = Pin(dc, Pin.OUT, value=0)
        self.rst = Pin(rst, Pin.OUT, value=1)
        self.busy = Pin(busy, Pin.IN, Pin.PULL_UP)  # LOW=忙

    def _cmd(self, c):
        self.dc(0); self.cs(0)
        self.spi.write(bytes([c]))
        self.cs(1)

    def _data(self, buf):
        self.dc(1); self.cs(0)
        self.spi.write(buf)
        self.cs(1)

    def _wait(self, timeout=60000):
        start = time.ticks_ms()
        while self.busy.value() == 0:
            if time.ticks_diff(time.ticks_ms(), start) > timeout:
                return False
            time.sleep_ms(20)
        return True

    def init(self):
        self.rst(0); time.sleep_ms(20)
        self.rst(1); time.sleep_ms(10)
        self.rst(0); time.sleep_ms(20)
        self.rst(1); time.sleep_ms(10)
        self._wait(10000)
        time.sleep_ms(10)
        self._cmd(0xE9)
        self._data(bytes([0x01]))

    def begin_frame(self):
        self._cmd(0x10)
        self._wait(10000)

    def write_chunk(self, buf):
        self.dc(1)
        self.cs(0)
        self.spi.write(buf)
        self.cs(1)

    def end_frame(self):
        self._cmd(0x04); self._wait(10000); time.sleep_ms(10)
        self._cmd(0x12); self._data(bytes([0x00])); time.sleep_ms(10); self._wait(40000)
        self._cmd(0x02); self._data(bytes([0x00])); self._wait(2000); time.sleep_ms(20)

    def sleep(self):
        self._cmd(0x07)
        self._data(bytes([0xA5]))