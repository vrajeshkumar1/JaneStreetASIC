# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
"""The five example programs in programs/, each run against a model of the
other end of the wire."""

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from bench import Bench

# ------------------------------------------------------------------- UART

UART_CLKDIV = 64                      # 65 clocks per tick, 8 ticks per bit
UART_BIT_CLOCKS = 8 * (UART_CLKDIV + 1)


@cocotb.test()
async def test_uart_tx(dut):
    """uart_tx.s: frames on the wire are correct and every bit is 8 ticks long."""
    b = Bench(dut)
    await b.reset()
    await b.load_file("uart_tx.s")
    b.settings(clkdiv=UART_CLKDIV, out_dir=0, side0="out4")
    await b.start()
    data = [0x55, 0x00, 0xFF, 0xA7, 0x31]
    for byte in data:
        await b.push(byte)

    def tx():
        return (int(dut.uo_out.value) >> 4) & 1

    # Record the line once per clock, starting when it first goes high (idle).
    while tx() == 0:
        await RisingEdge(dut.clk)
    trace = []
    for _ in range(UART_BIT_CLOCKS * 10 * (len(data) + 1)):
        await RisingEdge(dut.clk)
        trace.append(tx())

    # Decode: each frame is 10 bit periods starting at a falling edge.
    pos, got, starts = 0, [], []
    while len(got) < len(data):
        while trace[pos] == 1:
            pos += 1
        starts.append(pos)
        bits = [trace[pos + UART_BIT_CLOCKS * k + UART_BIT_CLOCKS // 2] for k in range(10)]
        assert bits[0] == 0 and bits[9] == 1, "start or stop bit wrong"
        got.append(sum(bit << i for i, bit in enumerate(bits[1:9])))
        # Every bit must last exactly one bit period: check each edge inside the frame.
        for k in range(1, 10):
            edge = pos + UART_BIT_CLOCKS * k
            assert trace[edge - 1] == bits[k - 1] and trace[edge] == bits[k], \
                f"bit boundary {k} is not exactly on the bit period"
        pos += UART_BIT_CLOCKS * 9 + UART_BIT_CLOCKS // 2
    assert got == data
    # Back-to-back frames are exactly 10 bit periods apart.
    assert {starts[i + 1] - starts[i] for i in range(len(starts) - 1)} == {UART_BIT_CLOCKS * 10}


async def uart_send(dut, byte, bit_clocks, stop=1):
    def rx(level):
        dut.ui_in.value = (int(dut.ui_in.value) & ~0x08) | (level << 3)
    rx(0)
    await ClockCycles(dut.clk, bit_clocks)
    for i in range(8):
        rx((byte >> i) & 1)
        await ClockCycles(dut.clk, bit_clocks)
    rx(stop)
    await ClockCycles(dut.clk, bit_clocks)
    rx(1)


@cocotb.test()
async def test_uart_rx(dut):
    """uart_rx.s: receives frames, tolerates a 2% fast or slow sender, and flags
    a missing stop bit without storing the byte."""
    b = Bench(dut)
    await b.reset()
    await b.load_file("uart_rx.s", entry="start")
    b.settings(clkdiv=UART_CLKDIV, in_dir=0)
    await b.start()
    await ClockCycles(dut.clk, 100)

    for byte in (0x55, 0x00, 0xFF, 0xA7):
        await uart_send(dut, byte, UART_BIT_CLOCKS)
        assert await b.pop() == byte
    for scale in (0.98, 1.02):
        for byte in (0x81, 0x7E):
            await uart_send(dut, byte, round(UART_BIT_CLOCKS * scale))
            assert await b.pop() == byte

    assert int(dut.flags.value) & 1 == 0
    await uart_send(dut, 0x42, UART_BIT_CLOCKS, stop=0)      # broken frame
    await ClockCycles(dut.clk, UART_BIT_CLOCKS * 2)
    assert int(dut.flags.value) & 1 == 1, "framing error was not flagged"
    assert dut.rx_empty.value == 1, "a byte with a bad stop bit was stored"
    await uart_send(dut, 0x99, UART_BIT_CLOCKS)              # recovers
    assert await b.pop() == 0x99


# -------------------------------------------------------------------- SPI

@cocotb.test()
async def test_spi_controller(dut):
    """spi_controller.s against a mode 0 target that answers with known bytes."""
    b = Bench(dut)
    await b.reset()
    await b.load_file("spi_controller.s")
    b.settings(clkdiv=2, out_dir=1, in_dir=1, autopull=1, autopush=1, side0="io3")

    ext = 0xF7                           # pull-down on the clock line
    dut.io_ext.value = ext
    await ClockCycles(dut.clk, 2)

    sent = [0xA5, 0x3C, 0x00, 0xFF, 0x81]
    reply = [0x5A, 0xC3, 0xFF, 0x00, 0x7E]
    seen = []

    def line(n):
        return (int(dut.io_line.value) >> n) & 1

    async def target():
        """Mode 0: sample MOSI on the rising clock edge, change MISO on the falling edge."""
        for out_byte in reply:
            in_byte = 0
            for i in range(8):
                dut.io_ext.value = (ext & ~0x04) | (((out_byte >> (7 - i)) & 1) << 2)
                await RisingEdge(dut.clk)
                while line(3) == 0:
                    await RisingEdge(dut.clk)
                in_byte = (in_byte << 1) | line(1)
                while line(3) == 1:
                    await RisingEdge(dut.clk)
            seen.append(in_byte)

    task = cocotb.start_soon(target())
    await b.start()
    for byte in sent:
        await b.push(byte)
    got = [await b.pop() for _ in sent]
    await task
    assert seen == sent, f"target received {[hex(v) for v in seen]}"
    assert got == reply, f"controller received {[hex(v) for v in got]}"

    # The clock is 4 ticks per bit: 12 clocks at CLKDIV = 2.
    for byte in sent:
        await b.push(byte)
    while line(3) == 0:
        await RisingEdge(dut.clk)
    edges, clock, last = [], 0, 1
    while len(edges) < 9:
        await RisingEdge(dut.clk)
        clock += 1
        if line(3) != last:
            last = line(3)
            if last == 1:
                edges.append(clock)
    assert {edges[i + 1] - edges[i] for i in range(7)} == {12}


# -------------------------------------------------------------------- I2C

SCL, SDA = 6, 7


class I2CWire:
    """The two open-drain lines as the outside world sees them."""

    def __init__(self, dut):
        self.dut = dut
        # Keep our own copy of what we drive: a value written to the simulator
        # cannot be read back until the next time step.
        self.ext = 0xFF
        dut.io_ext.value = self.ext

    def scl(self):
        return (int(self.dut.io_line.value) >> SCL) & 1

    def sda(self):
        return (int(self.dut.io_line.value) >> SDA) & 1

    def pull(self, bit, low):
        self.ext = (self.ext & ~(1 << bit)) if low else (self.ext | (1 << bit))
        self.dut.io_ext.value = self.ext


class I2CTargetModel:
    """A register-map device on the bus, for testing the controller program."""

    def __init__(self, dut, address):
        self.w = I2CWire(dut)
        self.dut = dut
        self.address = address
        self.mem = {}
        self.pointer = 0
        self.log = []
        self.stretch_clocks = 0

    async def _edge(self):
        """Wait for the next change on either line. Returns 'start', 'stop', 'rise' or 'fall'."""
        scl, sda = self.w.scl(), self.w.sda()
        while True:
            await RisingEdge(self.dut.clk)
            nscl, nsda = self.w.scl(), self.w.sda()
            if scl and nscl and sda and not nsda:
                return "start"
            if scl and nscl and not sda and nsda:
                return "stop"
            if not scl and nscl:
                return "rise"
            if scl and not nscl:
                return "fall"
            scl, sda = nscl, nsda

    async def _byte(self):
        """Receive 8 bits. Returns the byte, or 'start' / 'stop'."""
        value = 0
        for _ in range(8):
            while True:
                e = await self._edge()
                if e in ("start", "stop"):
                    return e
                if e == "rise":
                    value = (value << 1) | self.w.sda()
                    break
            while True:
                e = await self._edge()
                if e in ("start", "stop"):
                    return e
                if e == "fall":
                    break
        return value

    async def _ack(self, ack=True):
        self.w.pull(SDA, ack)
        if self.stretch_clocks:
            self.w.pull(SCL, True)
            await ClockCycles(self.dut.clk, self.stretch_clocks)
            self.w.pull(SCL, False)
        while await self._edge() != "rise":
            pass
        while await self._edge() != "fall":
            pass
        self.w.pull(SDA, False)

    async def _send(self, byte):
        for i in range(8):
            self.w.pull(SDA, not ((byte >> (7 - i)) & 1))
            while await self._edge() != "rise":
                pass
            while await self._edge() != "fall":
                pass
        self.w.pull(SDA, False)
        while await self._edge() != "rise":
            pass
        nack = self.w.sda()
        while True:
            e = await self._edge()
            if e == "fall":
                break
            if e in ("start", "stop"):
                return e
        return "nack" if nack else "ack"

    async def run(self):
        state = "idle"
        while True:
            if state == "idle":
                while await self._edge() != "start":
                    pass
                state = "address"
            if state == "address":
                self.log.append("start")
                while await self._edge() != "fall":
                    pass
                first = await self._byte()
                if first in ("start", "stop"):
                    state = "address" if first == "start" else "idle"
                    continue
                if first >> 1 != self.address:
                    state = "idle"
                    continue
                await self._ack()
                if first & 1:
                    while True:
                        r = await self._send(self.mem.get(self.pointer, 0xEE))
                        self.pointer = (self.pointer + 1) & 0xFF
                        if r != "ack":
                            break
                    state = "address" if r == "start" else "idle"
                    if r == "stop":
                        self.log.append("stop")
                    continue
                got_pointer = False
                while True:
                    value = await self._byte()
                    if value == "start":
                        state = "address"
                        break
                    if value == "stop":
                        self.log.append("stop")
                        state = "idle"
                        break
                    if not got_pointer:
                        self.pointer, got_pointer = value, True
                    else:
                        self.mem[self.pointer] = value
                        self.pointer = (self.pointer + 1) & 0xFF
                    await self._ack()


@cocotb.test()
async def test_i2c_controller(dut):
    """i2c_controller.s against a register-map device: write, read back with a
    repeated start, a missing device, clock stretching, and the clock timing."""
    b = Bench(dut)
    await b.reset()
    await b.load_file("i2c_controller.s")
    clkdiv = 9                                   # 10 clocks per tick, 60 per bit
    b.settings(clkdiv=clkdiv, out_dir=1, in_dir=1, side0="io6", open_drain=["io6", "io7"])
    L = b.labels
    device = I2CTargetModel(dut, 0x50)
    cocotb.start_soon(device.run())
    await b.start()

    async def cmd(name, data=None):
        await b.push(L[name])
        if data is not None:
            await b.push(data)

    async def write(byte):
        await cmd("write", byte)
        return await b.pop()

    # Write three registers starting at 0x10.
    await cmd("start")
    assert await write(0x50 << 1) == 0, "address not acknowledged"
    assert await write(0x10) == 0
    for value in (0xDE, 0xAD, 0x42):
        assert await write(value) == 0
    await cmd("stop")
    await ClockCycles(dut.clk, 400)
    assert device.mem == {0x10: 0xDE, 0x11: 0xAD, 0x12: 0x42}

    # Read them back: set the pointer, repeated start, read with ack, ack, nack.
    await cmd("start")
    assert await write(0x50 << 1) == 0
    assert await write(0x10) == 0
    await cmd("start")
    assert await write((0x50 << 1) | 1) == 0
    got = []
    for last in (False, False, True):
        await cmd("read")
        got.append(await b.pop())
        await cmd("nack" if last else "ack")
    await cmd("stop")
    await ClockCycles(dut.clk, 400)
    assert got == [0xDE, 0xAD, 0x42]

    # An address nobody answers is reported as not acknowledged.
    await cmd("start")
    assert await write(0x22 << 1) == 1
    await cmd("stop")
    await ClockCycles(dut.clk, 400)

    # A device that holds the clock low: the controller waits and still works.
    device.stretch_clocks = 150
    await cmd("start")
    assert await write(0x50 << 1) == 0
    assert await write(0x20) == 0
    assert await write(0x77) == 0
    await cmd("stop")
    await ClockCycles(dut.clk, 400)
    assert device.mem[0x20] == 0x77
    device.stretch_clocks = 0

    # Clock timing inside a byte: 6 ticks per bit, high for 3 and low for 3.
    w = I2CWire(dut)
    await cmd("start")
    await cmd("write", 0xA0)
    rises, falls, clock, last = [], [], 0, w.scl()
    while len(rises) < 8:
        await RisingEdge(dut.clk)
        clock += 1
        now = w.scl()
        if now != last:
            (rises if now else falls).append(clock)
            last = now
    tick = clkdiv + 1
    assert {rises[i + 1] - rises[i] for i in range(1, 7)} == {6 * tick}
    high = {f - r for r, f in zip(rises[1:7], [f for f in falls if f > rises[1]])}
    assert high == {3 * tick}, f"clock high time {high}"


class I2CControllerModel:
    """Bit-banged controller on the bus, for testing the target program."""

    def __init__(self, dut, half_clocks):
        self.w = I2CWire(dut)
        self.dut = dut
        self.h = half_clocks

    async def _t(self, n=1):
        await ClockCycles(self.dut.clk, self.h * n)

    async def start(self):
        self.w.pull(SDA, False)
        await self._t()
        self.w.pull(SCL, False)
        await self._t()
        self.w.pull(SDA, True)
        await self._t()
        self.w.pull(SCL, True)
        await self._t()

    async def stop(self):
        self.w.pull(SDA, True)
        await self._t()
        self.w.pull(SCL, False)
        await self._t()
        self.w.pull(SDA, False)
        await self._t()

    async def _clock(self):
        """One clock pulse; returns SDA sampled while the clock is high."""
        await self._t()
        self.w.pull(SCL, False)
        await self._t()
        bit = self.w.sda()
        self.w.pull(SCL, True)
        return bit

    async def write(self, byte):
        for i in range(8):
            self.w.pull(SDA, not ((byte >> (7 - i)) & 1))
            await self._clock()
        self.w.pull(SDA, False)
        nack = await self._clock()
        return not nack

    async def read(self, ack):
        value = 0
        self.w.pull(SDA, False)
        for _ in range(8):
            value = (value << 1) | await self._clock()
        self.w.pull(SDA, ack)
        await self._clock()
        self.w.pull(SDA, False)
        return value


@cocotb.test()
async def test_i2c_target(dut):
    """i2c_target.s at 400 kHz: answers only its own address, stores written
    bytes in the data memory, reads them back, and follows a repeated start."""
    b = Bench(dut)
    await b.reset()
    await b.load_file("i2c_target.s")
    b.settings(clkdiv=0, out_dir=1, in_dir=1, open_drain=["io6", "io7"])
    await b.set_reg(7, 0x3A << 1)
    for addr in range(16):
        await b.dm_write(addr, 0xC0 + addr)
    await b.start()
    await ClockCycles(dut.clk, 20)

    c = I2CControllerModel(dut, half_clocks=75)      # 150 clocks per bit = 400 kHz

    # Another device's address: no acknowledge, memory untouched.
    await c.start()
    assert not await c.write(0x3B << 1)
    await c.stop()

    # Write registers 5, 6, 7.
    await c.start()
    assert await c.write(0x3A << 1)
    assert await c.write(5)
    for value in (0x11, 0x22, 0x33):
        assert await c.write(value)
    await c.stop()
    assert [await b.dm_read(a) for a in (4, 5, 6, 7, 8)] == [0xC4, 0x11, 0x22, 0x33, 0xC8]

    # Set the pointer to 6, repeated start, read four bytes.
    await c.start()
    assert await c.write(0x3A << 1)
    assert await c.write(6)
    await c.start()
    assert await c.write((0x3A << 1) | 1)
    got = [await c.read(ack=(i < 3)) for i in range(4)]
    await c.stop()
    assert got == [0x22, 0x33, 0xC8, 0xC9]

    # The pointer wraps at 16.
    await c.start()
    assert await c.write(0x3A << 1)
    assert await c.write(15)
    assert await c.write(0xAA)
    assert await c.write(0xBB)
    await c.stop()
    assert await b.dm_read(15) == 0xAA
    assert await b.dm_read(0) == 0xBB
    assert dut.halted.value == 0
