# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: Apache-2.0
"""The Analog Discovery as the host: the same SPI transfers as the
MicroPython link in pe_host.py, made by the AD's digital pins through the
WaveForms SDK, so the FPGA build can be checked from a PC with no
microcontroller.

Needs WaveForms installed (it provides dwf.dll) and WaveForms itself closed,
since only one program can hold the device. Wiring:

    AD DIO 0  ->  JA1   host select
    AD DIO 1  ->  JA2   SPI clock
    AD DIO 2  ->  JA3   data to the chip
    AD DIO 3  <-  JB1   data from the chip
    AD ground ->  a GND pin of JA or JB

From the top of the repository:

    python firmware/ad3_host.py            self-test
    python firmware/ad3_host.py --uart     then leave uart_tx sending on
                                           out4 (JB7) for the logic analyser

The script closes the device at the end, so WaveForms can open it again; the
design keeps running (host select has a pull-up on the FPGA).
"""

import ctypes
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SEL, SCK, MOSI, MISO = 0, 1, 2, 3     # AD digital pins
SPI_HZ = 1_000_000                    # the chip allows up to 1/8 of its clock


def load_dwf():
    if sys.platform.startswith("win"):
        return ctypes.cdll.dwf
    if sys.platform == "darwin":
        return ctypes.cdll.LoadLibrary("/Library/Frameworks/dwf.framework/dwf")
    return ctypes.cdll.LoadLibrary("libdwf.so")


class AD3Link:
    """A pe_host link: begin(), xfer(bytes) -> bytes, end()."""

    def __init__(self, dwf=None, device=-1):
        self.dwf = dwf or load_dwf()
        self.hdwf = ctypes.c_int()
        if not self.dwf.FDwfDeviceOpen(ctypes.c_int(device), ctypes.byref(self.hdwf)) \
                or self.hdwf.value == 0:
            msg = ctypes.create_string_buffer(512)
            self.dwf.FDwfGetLastErrorMsg(msg)
            raise OSError("Analog Discovery not opened: " + msg.value.decode(errors="replace"))
        d, h = self.dwf, self.hdwf
        self._check(d.FDwfDigitalSpiReset(h))
        self._check(d.FDwfDigitalSpiFrequencySet(h, ctypes.c_double(SPI_HZ)))
        self._check(d.FDwfDigitalSpiClockSet(h, ctypes.c_int(SCK)))
        self._check(d.FDwfDigitalSpiDataSet(h, ctypes.c_int(0), ctypes.c_int(MOSI)))
        self._check(d.FDwfDigitalSpiDataSet(h, ctypes.c_int(1), ctypes.c_int(MISO)))
        self._check(d.FDwfDigitalSpiModeSet(h, ctypes.c_int(0)))     # CPOL 0, CPHA 0
        self._check(d.FDwfDigitalSpiOrderSet(h, ctypes.c_int(1)))    # highest bit first
        self.end()

    def _check(self, ok):
        if not ok:
            msg = ctypes.create_string_buffer(512)
            self.dwf.FDwfGetLastErrorMsg(msg)
            raise OSError("WaveForms SDK: " + msg.value.decode(errors="replace"))

    def begin(self):
        self._check(self.dwf.FDwfDigitalSpiSelect(self.hdwf, ctypes.c_int(SEL), ctypes.c_int(0)))

    def end(self):
        self._check(self.dwf.FDwfDigitalSpiSelect(self.hdwf, ctypes.c_int(SEL), ctypes.c_int(1)))

    def xfer(self, data):
        n = len(data)
        tx = (ctypes.c_ubyte * n)(*data)
        rx = (ctypes.c_ubyte * n)()
        # transfer type 1: MOSI / MISO; 8 bits per word
        self._check(self.dwf.FDwfDigitalSpiWriteRead(self.hdwf, ctypes.c_int(1), ctypes.c_int(8),
                                                     tx, ctypes.c_int(n), rx, ctypes.c_int(n)))
        return bytearray(rx)

    def close(self):
        self.dwf.FDwfDeviceClose(self.hdwf)


def main():
    import demo
    import make_programs
    from pe_host import Chip

    programs = make_programs.build()
    link = AD3Link()
    try:
        chip = Chip(link)
        demo.selftest(chip, programs)
        print("link, sizes, engines and flags: ok")
        if "--uart" in sys.argv:
            chip.enable(0)
            chip.restart(1)
            chip.load(0, programs["uart_tx"])
            chip.configure(0, clkdiv=64, side0="out4")      # 115,385 baud at 60 MHz
            chip.pins(out={4: 0})
            chip.start(0)
            chip.drive(out=[4])
            for _ in range(20):
                chip.push(0, list(b"hello\r\n"))
                time.sleep(0.01)
            print("uart_tx on out4 (JB7): 115200 baud, 8N1, \"hello\" sent 20 times;"
                  " push more with the TX FIFO, or rerun")
    finally:
        link.close()


if __name__ == "__main__":
    main()
