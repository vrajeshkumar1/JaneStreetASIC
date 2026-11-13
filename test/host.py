# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
"""The host's side of the chip, for the tests: the wires outside the chip and
an SPI controller that speaks the host link of docs/spec.md, part 2.

The SPI clock here is timed in nanoseconds, not in chip clocks, so it is not
lined up with the chip clock, as on the real board."""

import os
import sys

from cocotb.triggers import Timer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from pasm import assemble  # noqa: E402

# ---- global registers
ID, VERSION, ENABLE, RESTART = 0x00, 0x01, 0x02, 0x03
FLAGS, FLAGS_SET, FLAGS_CLR = 0x04, 0x05, 0x06
ATTN_MASK, CTRL, STATUS = 0x07, 0x08, 0x09
OWNER_OUT, OWNER_IO = 0x10, 0x12
DRIVE_OUT, DRIVE_IO, OPEN_DRAIN = 0x14, 0x15, 0x16

# ---- engine registers (offsets)
E_CFG, E_PULL_THRESH, E_PUSH_THRESH, E_CLKDIV = 0x00, 0x01, 0x02, 0x03
E_SIDE0, E_SIDE1, E_PC, E_STATUS = 0x05, 0x06, 0x07, 0x09
E_TX_LEVEL, E_RX_LEVEL, E_FIFO, E_DEBUG = 0x0A, 0x0B, 0x0C, 0x0D
E_CRC_POLY, E_CRC_WIDTH, E_SIZES, E_CRC, E_DM_SIZE, E_R0 = 0x0E, 0x12, 0x13, 0x14, 0x18, 0x20

# ---- engine STATUS bits
ST_RUNNING, ST_STALLED, ST_HALTED, ST_ILLEGAL = 0x01, 0x02, 0x04, 0x08
ST_TX_EMPTY, ST_TX_FULL, ST_RX_EMPTY, ST_RX_FULL = 0x10, 0x20, 0x40, 0x80


def ereg(e, offset):
    return 0x0100 + 0x40 * e + offset


def dmem(e, offset=0):
    return 0x0200 + 0x10 * e + offset


def prog(e, word=0):
    return 0x4000 + 0x800 * e + 4 * word


def pin(name):
    """Number of a writable pin, as SIDE0/SIDE1 and the instructions use it."""
    kind, n = name[:-1], int(name[-1])
    return {"out": 0, "io": 8}[kind] + n


class Wires:
    """What the outside world puts on the chip's pins. The values written are
    kept here as well, because a value written to the simulator cannot be read
    back until the next time step, and several models share these two buses."""

    def __init__(self, dut, ui=0x01):
        self.dut = dut
        self.ui = ui            # default: host select high, everything else low
        self.ext = 0xFF         # pull-ups on all bidirectional lines
        dut.ui_in.value = self.ui
        dut.io_ext.value = self.ext

    def set_in(self, n, level):
        """Drive input pin n."""
        self.ui = (self.ui | (1 << n)) if level else (self.ui & ~(1 << n))
        self.dut.ui_in.value = self.ui

    def pull(self, n, low):
        """Hold bidirectional line n low from outside, or let it go."""
        self.ext = (self.ext & ~(1 << n)) if low else (self.ext | (1 << n))
        self.dut.io_ext.value = self.ext

    def io(self, n):
        return (int(self.dut.io_line.value) >> n) & 1

    def out(self, n):
        return (int(self.dut.uo_out.value) >> n) & 1


class Host:
    """SPI controller on the three borrowed pins plus host select."""

    SEL, SCK, MOSI, MISO = 0, 1, 2, 0

    def __init__(self, wires, half_ns=71):
        self.w = wires
        self.half_ns = half_ns          # half of the SPI clock period

    async def _half(self):
        await Timer(self.half_ns, "ns")

    async def _begin(self):
        """Select the chip. The SPI pins are moved to their idle levels only
        after host select is low, so the engines never see them move."""
        self.restore = (self.w.ui >> self.SCK) & 3
        self.w.set_in(self.SEL, 0)
        await self._half()
        await self._half()
        self.w.set_in(self.SCK, 0)
        await self._half()

    async def _end(self):
        """Put SCK and MOSI back to what they were, then release the chip."""
        self.w.set_in(self.MOSI, (self.restore >> 1) & 1)
        self.w.set_in(self.SCK, self.restore & 1)
        await self._half()
        self.w.set_in(self.SEL, 1)
        await self._half()
        await self._half()

    async def _byte(self, value=0):
        got = 0
        for i in range(7, -1, -1):
            self.w.set_in(self.MOSI, (value >> i) & 1)
            await self._half()
            got = (got << 1) | self.w.out(self.MISO)     # sample, then raise the clock
            self.w.set_in(self.SCK, 1)
            await self._half()
            self.w.set_in(self.SCK, 0)
        return got

    # ------------------------------------------------------------ transfers
    async def write(self, addr, data):
        if isinstance(data, int):
            data = [data]
        await self._begin()
        await self._byte(0x80 | (addr >> 8))
        await self._byte(addr & 0xFF)
        for value in data:
            await self._byte(value)
        await self._end()

    async def read(self, addr, n=1):
        await self._begin()
        await self._byte(addr >> 8)
        await self._byte(addr & 0xFF)
        await self._byte()                               # dummy
        got = [await self._byte() for _ in range(n)]
        await self._end()
        return got

    async def read1(self, addr):
        return (await self.read(addr, 1))[0]

    # -------------------------------------------------------------- engines
    async def load(self, e, source, entry=None):
        """Assemble a program, store it in engine e's memory, set its entry
        point. Returns the assembled program (words, labels)."""
        program = assemble(source)
        data = []
        for word in program.words:
            data += [(word >> s) & 0xFF for s in (0, 8, 16, 24)]
        await self.write(prog(e), data)
        await self.set_pc(e, program.labels[entry] if entry else 0)
        return program

    async def load_file(self, e, name, entry=None):
        with open(os.path.join(ROOT, "programs", name)) as f:
            return await self.load(e, f.read(), entry)

    async def configure(self, e, clkdiv=0, out_dir=0, in_dir=0, autopull=0, autopush=0,
                        crc_dir=0, pull_thresh=8, push_thresh=8,
                        side0=None, side1=None, side0_dir=False, side1_dir=False):
        """Engine settings. side0 / side1 are pin names such as "out4" or "io6"."""
        def side(name, direction):
            if name is None:
                return 0
            return 0x10 | pin(name) | (0x20 if direction else 0)
        cfg = out_dir | (in_dir << 1) | (autopull << 2) | (autopush << 3) | (crc_dir << 4)
        await self.write(ereg(e, E_CFG), [cfg, pull_thresh, push_thresh,
                                          clkdiv & 0xFF, clkdiv >> 8,
                                          side(side0, side0_dir), side(side1, side1_dir)])

    async def pins(self, out=None, io=None, open_drain=()):
        """Give pins to engines. out / io: {pin number: engine}.
        open_drain: bidirectional pin numbers. The drivers stay off."""
        out, io = out or {}, io or {}
        owner_out = sum(e << (2 * n) for n, e in out.items())
        owner_io = sum(e << (2 * n) for n, e in io.items())
        await self.write(OWNER_OUT, [owner_out & 0xFF, owner_out >> 8,
                                     owner_io & 0xFF, owner_io >> 8])
        await self.write(OPEN_DRAIN, sum(1 << n for n in open_drain))

    async def drive(self, out=(), io=()):
        """Switch pin drivers on (and all others off). Done after the engines
        have started, so that each program has set its pin levels first."""
        await self.write(DRIVE_OUT, [sum(1 << n for n in out), sum(1 << n for n in io)])

    async def set_pc(self, e, address):
        await self.write(ereg(e, E_PC), [address & 0xFF, address >> 8])

    async def pc(self, e):
        lo, hi = await self.read(ereg(e, E_PC), 2)
        return lo | (hi << 8)

    async def sizes(self, e):
        """-> (program words, FIFO bytes, data memory bytes) of engine e."""
        s = await self.read1(ereg(e, E_SIZES))
        d = await self.read1(ereg(e, E_DM_SIZE))
        return 1 << (s & 15), 1 << (s >> 4), 1 << (d & 15)

    async def enable(self, mask):
        await self.write(ENABLE, mask)

    async def restart(self, mask):
        await self.write(RESTART, mask)

    async def push(self, e, data):
        await self.write(ereg(e, E_FIFO), data)

    async def pop(self, e, n=1):
        return await self.read(ereg(e, E_FIFO), n)

    async def status(self, e):
        return await self.read1(ereg(e, E_STATUS))

    async def rx_level(self, e):
        return await self.read1(ereg(e, E_RX_LEVEL))

    async def reg(self, e, n):
        lo, hi = await self.read(ereg(e, E_R0 + 2 * n), 2)
        return lo | (hi << 8)

    async def set_reg(self, e, n, value):
        await self.write(ereg(e, E_R0 + 2 * n), [value & 0xFF, value >> 8])

    async def wait_rx(self, e, n, tries=200):
        """Poll until engine e's RX FIFO holds n bytes, then read them."""
        for _ in range(tries):
            if await self.rx_level(e) >= n:
                return await self.pop(e, n)
        raise AssertionError(f"engine {e}: {n} bytes did not arrive")

    async def wait_halt(self, e, tries=200):
        for _ in range(tries):
            st = await self.status(e)
            if st & ST_HALTED:
                return st
        raise AssertionError(f"engine {e} did not halt")
