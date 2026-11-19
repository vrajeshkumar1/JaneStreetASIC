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
    python firmware/ad3_host.py --diag     raw bytes of an ID read, and a
                                           check of host select on LED 2

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
# The chip allows up to 1/8 of its clock (7.5 MHz). Measured with --sweep on
# an Analog Discovery 3: at 500 kHz and below the AD reads the chip's data one
# bit late every time, at 1 MHz some of the time, and at 2 and 4 MHz never.
# The chip changes its data bit up to 5 chip clocks after each rising edge,
# and the AD evidently reads it later after the edge at lower clock rates.
SPI_HZ = 4_000_000
PAD = 7                               # bits after each transfer, see AD3Link.xfer


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
        self._check(d.FDwfDigitalSpiClockSet(h, ctypes.c_int(SCK)))
        self._check(d.FDwfDigitalSpiDataSet(h, ctypes.c_int(0), ctypes.c_int(MOSI)))
        self._check(d.FDwfDigitalSpiDataSet(h, ctypes.c_int(1), ctypes.c_int(MISO)))
        self._check(d.FDwfDigitalSpiModeSet(h, ctypes.c_int(0)))     # CPOL 0, CPHA 0
        self._check(d.FDwfDigitalSpiOrderSet(h, ctypes.c_int(1)))    # highest bit first
        # Frequency last: --sweep, which set it after the mode, read correctly
        # at 4 MHz while the self-test, with it set before, did not.
        self._check(d.FDwfDigitalSpiFrequencySet(h, ctypes.c_double(SPI_HZ)))
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

    def _write_read(self, bits_per_word, words):
        n = len(words)
        tx = (ctypes.c_ubyte * n)(*words)
        rx = (ctypes.c_ubyte * n)()
        # transfer type 1: MOSI / MISO
        self._check(self.dwf.FDwfDigitalSpiWriteRead(self.hdwf, ctypes.c_int(1),
                                                     ctypes.c_int(bits_per_word),
                                                     tx, ctypes.c_int(n), rx, ctypes.c_int(n)))
        return list(rx)

    def xfer(self, data):
        """Measured with --mosi on an Analog Discovery 3: the last few bits
        the AD reads in each SPI call come back as 0, while everything it
        sends arrives. So a transfer is sent one bit per SPI word with PAD
        extra bits after it. The chip discards an unfinished byte, so the
        padding writes nothing and takes nothing from a FIFO. Long transfers
        (program loads, which read nothing) go eight bits per word, in
        pieces, with the same padding at the end."""
        data = list(data)
        if len(data) > 64:
            for k in range(0, len(data), 256):
                self._write_read(8, data[k:k + 256])
            self._write_read(1, [0] * PAD)
            return bytearray(len(data))
        bits = [(b >> (7 - i)) & 1 for b in data for i in range(8)]
        got = self._write_read(1, bits + [0] * PAD)
        out = bytearray(len(data))
        for k in range(len(data)):
            v = 0
            for i in range(8):
                v = (v << 1) | (got[8 * k + i] & 1)
            out[k] = v
        return out

    def close(self):
        self.dwf.FDwfDeviceClose(self.hdwf)


def diagnose(link):
    """Raw bytes of an ID read at two clock rates, then host select held low
    for three seconds so the PYNQ's LED 2 can be checked."""
    d, h = link.dwf, link.hdwf
    for hz in (1_000_000, 100_000):
        link._check(d.FDwfDigitalSpiFrequencySet(h, ctypes.c_double(hz)))
        link.begin()
        got = link.xfer([0x00, 0x00, 0x00, 0x00, 0x00])    # read ID and VERSION
        link.end()
        print("%7d Hz: sent 00 00 00 00 00, got %s (expect .. .. .. 4A, then the version)"
              % (hz, " ".join("%02X" % b for b in got)))
    link._check(d.FDwfDigitalSpiFrequencySet(h, ctypes.c_double(SPI_HZ)))
    print("host select low for 3 s: LED 2 on the PYNQ should light")
    link.begin()
    time.sleep(3)
    link.end()
    print("released: LED 2 should be off. LED 0 should be on (clock locked), LED 1 off (not in reset)")


def sweep(link):
    """Where in the bit the AD samples the chip's data: reads ID, VERSION and
    two zero registers 20 times at each SPI clock rate, in SPI modes 0 and 1
    (the data sent is all zeros, so mode 1 changes only when the AD samples).
    Expected bytes: 4A 01 00 00."""
    d, h = link.dwf, link.hdwf
    for mode in (0, 1):
        link._check(d.FDwfDigitalSpiModeSet(h, ctypes.c_int(mode)))
        for hz in (50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000, 4_000_000):
            link._check(d.FDwfDigitalSpiFrequencySet(h, ctypes.c_double(hz)))
            seen = {}
            for _ in range(20):
                link.begin()
                got = link.xfer([0] * 7)
                link.end()
                key = " ".join("%02X" % b for b in got[3:])
                seen[key] = seen.get(key, 0) + 1
            print("mode %d %8d Hz: %s" % (mode, hz, ", ".join(
                "%s x%d" % kv for kv in sorted(seen.items(), key=lambda kv: -kv[1]))))
    link._check(d.FDwfDigitalSpiModeSet(h, ctypes.c_int(0)))
    link._check(d.FDwfDigitalSpiFrequencySet(h, ctypes.c_double(SPI_HZ)))


def mosi_check(link):
    """Checks that the chip receives the AD's data correctly: reads at
    non-zero addresses and a write followed by a read back, at 2 and 4 MHz."""
    from pe_host import Chip
    d, h = link.dwf, link.hdwf
    chip = Chip(link)
    for hz in (2_000_000, 4_000_000):
        link._check(d.FDwfDigitalSpiFrequencySet(h, ctypes.c_double(hz)))
        print("%d Hz:" % hz)
        for addr, name, want in ((0x0001, "VERSION", 0x01), (0x0113, "engine 0 SIZES", 0x38),
                                 (0x01D3, "engine 3 SIZES", 0x48), (0x0119, "engine 0 FEATURES", 0x00),
                                 (0x01D9, "engine 3 FEATURES", 0x03)):
            got = chip.read1(addr)
            print("  read %04X %-18s got %02X, expect %02X%s" % (addr, name, got, want,
                                                               "" if got == want else "   <-- wrong"))
        for value in (0xA5, 0x5A, 0x01, 0x80):
            chip.clear_flags(0xFF)
            chip.set_flags(value)
            got = chip.flags()
            print("  write FLAGS %02X, read back %02X%s" % (value, got, "" if got == value else "   <-- wrong"))
        chip.clear_flags(0xFF)
    link._check(d.FDwfDigitalSpiFrequencySet(h, ctypes.c_double(SPI_HZ)))


def main():
    import demo
    import make_programs
    from pe_host import Chip

    programs = make_programs.build()
    link = AD3Link()
    try:
        if "--mosi" in sys.argv:
            mosi_check(link)
            return
        if "--sweep" in sys.argv:
            sweep(link)
            return
        if "--diag" in sys.argv:
            diagnose(link)
            return
        chip = Chip(link)
        link.begin()
        raw = link.xfer([0] * 7)
        link.end()
        print("ID read: %s (expect .. .. .. 4A 01 00 00)" % " ".join("%02X" % b for b in raw))
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
