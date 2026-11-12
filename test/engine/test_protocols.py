# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
"""The five example programs in programs/, each run against a model of the
other end of the wire."""

import os
import sys

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from bench import Bench

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from host import Wires  # noqa: E402
from models import SCL, I2CControllerModel, I2CTargetModel  # noqa: E402

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
    wires = Wires(dut, ui=0xFF)
    device = I2CTargetModel(wires, 0x50)
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
    await cmd("start")
    await cmd("write", 0xA0)
    rises, falls, clock, last = [], [], 0, wires.io(SCL)
    while len(rises) < 8:
        await RisingEdge(dut.clk)
        clock += 1
        now = wires.io(SCL)
        if now != last:
            (rises if now else falls).append(clock)
            last = now
    tick = clkdiv + 1
    assert {rises[i + 1] - rises[i] for i in range(1, 7)} == {6 * tick}
    high = {f - r for r, f in zip(rises[1:7], [f for f in falls if f > rises[1]])}
    assert high == {3 * tick}, f"clock high time {high}"


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

    c = I2CControllerModel(Wires(dut, ui=0xFF), half_clocks=75)      # 150 clocks per bit = 400 kHz

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
