# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
"""Tests of the whole chip through its pins: the host link, the registers,
program loading, pin sharing, and several engines running at once.

Everything goes through the SPI host model in host.py, as the firmware on the
demo board will, so the same tests run on the gate-level netlist."""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from host import (ATTN_MASK, CTRL, DRIVE_OUT, E_CFG, E_CRC_POLY, E_CRC_WIDTH, E_DEBUG,
                  E_FIFO, E_R0, E_TX_LEVEL, FLAGS, FLAGS_CLR, FLAGS_SET, ID,
                  OPEN_DRAIN, OWNER_OUT, ST_HALTED, ST_ILLEGAL, ST_RUNNING, ST_RX_EMPTY,
                  ST_RX_FULL, ST_STALLED, ST_TX_EMPTY, ST_TX_FULL, STATUS, Host, Wires,
                  dmem, ereg, prog)
from models import I2CTargetModel, spi_target

CLOCK_NS = 16.666  # 60 MHz

# (program words, FIFO bytes, data memory bytes) of each engine
SIZES = {0: (256, 8, 4), 1: (256, 8, 4), 2: (512, 8, 4), 3: (256, 16, 16)}


async def start(dut, half_ns=71):
    """Reset the chip. Returns the wires and the host."""
    cocotb.start_soon(Clock(dut.clk, CLOCK_NS, unit="ns").start())
    w = Wires(dut)
    dut.ena.value = 1
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    return w, Host(w, half_ns)


# ------------------------------------------------------------- registers

@cocotb.test()
async def test_registers(dut):
    """Reset values, and every writable register of every engine holds what
    was written without disturbing its neighbours."""
    w, h = await start(dut)

    assert await h.read(ID, 3) == [0x4A, 0x01, 0x00]
    for e in range(4):
        assert await h.read(ereg(e, E_CFG), 3) == [0x00, 8, 8]
        assert await h.read1(ereg(e, E_CRC_WIDTH)) == 32
        assert await h.status(e) == ST_TX_EMPTY | ST_RX_EMPTY
        assert await h.sizes(e) == SIZES[e]

    # Global registers. The drive enables are written too: every engine's pin
    # levels are 0 after reset, so nothing changes on the pins.
    globals_ = {ATTN_MASK: [0xA5], OWNER_OUT: [0x1B, 0xE4, 0x4E, 0xB1, 0x5A, 0xC3, 0x3C]}
    for addr, data in globals_.items():
        await h.write(addr, data)
    for addr, data in globals_.items():
        assert await h.read(addr, len(data)) == data

    # Engine registers: CFG .. SIDE1, the checksum settings, r0..r7 and the
    # data memory, with different values in every engine.
    rng = random.Random(7)
    expect = {}
    for e in range(4):
        cfg = [rng.getrandbits(5), rng.getrandbits(4), rng.getrandbits(4), rng.getrandbits(8),
               rng.getrandbits(8), rng.getrandbits(6), rng.getrandbits(6)]
        crc = [rng.getrandbits(8) for _ in range(4)] + [rng.getrandbits(6)]
        regs = [rng.getrandbits(8) for _ in range(16)]
        mem = [rng.getrandbits(8) for _ in range(SIZES[e][2])]
        expect[e] = (cfg, crc, regs, mem)
        await h.write(ereg(e, E_CFG), cfg)
        await h.write(ereg(e, E_CRC_POLY), crc)
        await h.write(ereg(e, E_R0), regs)
        await h.write(dmem(e), mem)
    for e in range(4):
        cfg, crc, regs, mem = expect[e]
        assert await h.read(ereg(e, E_CFG), 7) == cfg
        assert await h.read(ereg(e, E_CRC_POLY), 5) == crc
        assert await h.read(ereg(e, E_R0), 16) == regs
        assert await h.read(dmem(e), len(mem)) == mem
        if len(mem) < 16:                               # a smaller memory repeats
            assert await h.read(dmem(e, len(mem)), len(mem)) == mem

    # Addresses with nothing behind them read as zero.
    assert await h.read(0x0300, 2) == [0, 0]
    assert await h.read1(0x0030) == 0
    assert await h.read1(0x7FFF) == 0


@cocotb.test()
async def test_program_memory(dut):
    """Program memory holds what the host wrote, in all four engines, and is
    out of the host's reach while its engine runs. Uses a faster SPI clock
    (84 ns, about five chip clocks) to keep the test short."""
    w, h = await start(dut, half_ns=42)
    rng = random.Random(1)

    def as_bytes(words):
        return [(word >> s) & 0xFF for word in words for s in (0, 8, 16, 24)]

    full = [rng.getrandbits(32) for _ in range(256)]
    await h.write(prog(3), as_bytes(full))
    part = {e: [rng.getrandbits(32) for _ in range(4)] for e in range(3)}
    for e in range(3):
        await h.write(prog(e, 100 + e), as_bytes(part[e]))

    assert await h.read(prog(3), 1024) == as_bytes(full)
    for e in range(3):
        assert await h.read(prog(e, 100 + e), 16) == as_bytes(part[e])
    # Engine 2 has 512 words: word 300 is not word 44.
    await h.write(prog(2, 44), as_bytes([0xAAAA0044]))
    await h.write(prog(2, 300), as_bytes([0xBBBB0300]))
    assert await h.read(prog(2, 44), 4) == as_bytes([0xAAAA0044])
    assert await h.read(prog(2, 300), 4) == as_bytes([0xBBBB0300])
    # A read that starts inside a word and runs across word boundaries.
    assert await h.read(prog(3, 10) + 2, 7) == as_bytes(full[10:13])[2:9]

    # Engine 0 runs a one-instruction loop: the host can neither write nor
    # read its memory until it is stopped again.
    loop = await h.load(0, "loop: jmp loop")
    await h.write(prog(0, 50), as_bytes([0x11223344]))
    await h.enable(0b0001)
    await h.write(prog(0, 50), as_bytes([0xDEADBEEF]))
    assert await h.read(prog(0, 50), 4) == [0, 0, 0, 0]
    assert await h.status(0) & ST_RUNNING
    await h.enable(0)
    assert await h.read(prog(0, 50), 4) == as_bytes([0x11223344])
    assert await h.read(prog(0), 4) == as_bytes(loop.words)


# --------------------------------------------------------------- engines

@cocotb.test()
async def test_engine_program(dut):
    """Load a program over the host link, run it, read the results back; then
    restart at a different entry point."""
    w, h = await start(dut)
    e = 1
    p = await h.load(e, """
            set r0, 0x1234
            set r1, 5
    loop:   add r0, r0, 3
            jmp r1--, loop
            st r0, [@2]
            halt
    alt:    set r0, 0x00AA
            halt
    """)
    await h.enable(1 << e)
    st = await h.wait_halt(e)
    assert st == ST_HALTED | ST_TX_EMPTY | ST_RX_EMPTY
    assert await h.read1(STATUS) == 1 << e
    assert await h.reg(e, 0) == 0x1234 + 6 * 3
    assert await h.reg(e, 1) == 0xFFFF            # "rN--" counts down past zero
    assert await h.read1(dmem(e, 2)) == 0x46
    assert await h.pc(e) == 5
    # The other engines were not touched.
    for other in (0, 2, 3):
        assert await h.status(other) == ST_TX_EMPTY | ST_RX_EMPTY

    # Registers and the program counter are closed to the host while ENABLE is set.
    await h.set_reg(e, 0, 0xFFFF)
    await h.set_pc(e, 0)
    assert await h.reg(e, 0) == 0x1246
    assert await h.pc(e) == 5

    await h.enable(0)
    await h.restart(1 << e)
    assert await h.status(e) == ST_TX_EMPTY | ST_RX_EMPTY
    assert await h.pc(e) == 0
    await h.set_pc(e, p.labels["alt"])
    await h.enable(1 << e)
    await h.wait_halt(e)
    assert await h.reg(e, 0) == 0x00AA


@cocotb.test()
async def test_fifos(dut):
    """Host side of the FIFOs: levels, full and empty, the four DEBUG bits,
    and a read that stops part-way through a byte."""
    w, h = await start(dut)
    for e in (2, 3):                                    # an 8-byte and a 16-byte engine
        await fifo_checks(w, h, e, SIZES[e][1])


async def fifo_checks(w, h, e, depth):
    await h.load(e, """
    loop:   pull
            mov isr, osr, inv
            push
            jmp loop
    """)
    data = [0x30 + i for i in range(depth)]
    await h.push(e, data)
    assert await h.read1(ereg(e, E_TX_LEVEL)) == depth
    assert await h.status(e) == ST_TX_FULL | ST_RX_EMPTY
    assert await h.read1(ereg(e, E_DEBUG)) == 0
    await h.push(e, 0x99)                               # one too many
    assert await h.read1(ereg(e, E_DEBUG)) == 0x01
    await h.write(ereg(e, E_DEBUG), 0x01)
    assert await h.read1(ereg(e, E_DEBUG)) == 0

    await h.enable(1 << e)
    for _ in range(50):
        if await h.rx_level(e) == depth:
            break
    assert await h.rx_level(e) == depth
    assert await h.status(e) & ST_RX_FULL

    # Four clock pulses into the first data byte, then stop: nothing is lost.
    await h._begin()
    await h._byte(ereg(e, E_FIFO) >> 8)
    await h._byte(ereg(e, E_FIFO) & 0xFF)
    await h._byte()
    for _ in range(4):
        await h._half()
        w.set_in(h.SCK, 1)
        await h._half()
        w.set_in(h.SCK, 0)
    await h._end()
    assert await h.rx_level(e) == depth

    # With in1 idling high, every transfer ends with one extra rising edge on
    # the SPI clock pin (the host putting the pin back). It must not pop.
    w.set_in(1, 1)
    assert await h.pop(e, depth) == [v ^ 0xFF for v in data]
    assert await h.rx_level(e) == 0
    assert await h.read1(ereg(e, E_DEBUG)) == 0
    await h.pop(e, 1)                                   # nothing there
    assert await h.read1(ereg(e, E_DEBUG)) == 0x02
    await h.write(ereg(e, E_DEBUG), 0x02)
    assert await h.read1(ereg(e, E_DEBUG)) == 0

    # The two bits the engine sets: a pull that found nothing and a push that
    # found no room, both without waiting.
    await h.enable(0)
    await h.restart(1 << e)
    await h.load(e, f"""
            pull noblock
            set r0, {depth}
    fill:   mov isr, r0
            push noblock
            jmp r0--, fill
            halt
    """)
    await h.enable(1 << e)
    await h.wait_halt(e)
    assert await h.read1(ereg(e, E_DEBUG)) == 0x0C
    assert await h.rx_level(e) == depth
    await h.write(ereg(e, E_DEBUG), 0x04)
    assert await h.read1(ereg(e, E_DEBUG)) == 0x08
    await h.write(ereg(e, E_DEBUG), 0x08)
    assert await h.read1(ereg(e, E_DEBUG)) == 0
    assert await h.pop(e, 3) == [depth, depth - 1, depth - 2]

    # RESTART empties both FIFOs.
    await h.enable(0)
    await h.push(e, [1, 2, 3])
    await h.restart(1 << e)
    assert await h.read(ereg(e, E_TX_LEVEL), 2) == [0, 0]


@cocotb.test()
async def test_fast_host_clock(dut):
    """The host link at an SPI clock period of 100 ns, six chip clocks."""
    w, h = await start(dut, half_ns=50)
    assert await h.read(ID, 2) == [0x4A, 0x01]
    await h.load(0, """
    loop:   pull
            mov isr, osr
            push
            jmp loop
    """)
    await h.enable(1)
    data = [0x00, 0xFF, 0xA5, 0x5A, 0x81, 0x7E, 0x01, 0x80]
    await h.push(0, data)
    assert await h.wait_rx(0, 8) == data


@cocotb.test()
async def test_memory_block_data(dut):
    """ldm and stm: a program keeps data bytes in the spare part of its own
    memory block, and the host finds them there afterwards."""
    w, h = await start(dut)
    for e, base in ((0, 400), (2, 1600)):               # byte addresses: word 100, word 400
        word = base // 4
        await h.write(prog(e, word), [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        await h.load(e, f"""
                set r1, {base}
                ldm r2, [r1]          ; 0x11, written by the host
                add r1, r1, 3
                ldm r3, [r1]          ; 0x44
                set r0, 0xA5
                stm r0, [r1]          ; replace 0x44; its neighbours stay
                ldm r4, [r1]
                add r1, r1, 2
                set r0, 0x3C
                ifn stm r0, [r1]      ; T is 0: stored at byte 5
                ift stm r0, [r1]      ; skipped
                ldm r5, [r1]  [3]
                set r6, 0x77          ; runs after the delay, with the right instruction
                halt
        """)
        await h.enable(1 << e)
        await h.wait_halt(e)
        assert [await h.reg(e, n) for n in (2, 3, 4, 5, 6)] == [0x11, 0x44, 0xA5, 0x3C, 0x77]
        await h.enable(0)
        assert await h.read(prog(e, word), 8) == [0x11, 0x22, 0x33, 0xA5, 0x55, 0x3C, 0x77, 0x88]
        # The program itself is intact.
        await h.restart(1 << e)
        await h.enable(1 << e)
        await h.wait_halt(e)
        assert await h.reg(e, 3) == 0xA5
        await h.enable(0)


@cocotb.test()
async def test_large_program_memory(dut):
    """Engine 2 runs code above word 255, reached by a jump and by setting
    the program counter."""
    w, h = await start(dut, half_ns=42)
    e = 2
    p = await h.load(e, """
            set r0, 1
            jmp far
    back:   add r0, r0, 0x10
            halt
            .org 300
    far:    add r0, r0, 0x100
            mov r1, pc            ; 301
            call sub
            jmp back
    sub:    mov r2, lr            ; 303
            ret
    entry:  set r0, 0x7000
            halt
    """)
    assert p.labels["far"] == 300
    await h.enable(1 << e)
    await h.wait_halt(e)
    assert [await h.reg(e, n) for n in (0, 1, 2)] == [0x111, 301, 303]
    assert await h.pc(e) == 3
    await h.enable(0)
    await h.restart(1 << e)
    await h.set_pc(e, p.labels["entry"])
    assert await h.pc(e) == p.labels["entry"]
    await h.enable(1 << e)
    await h.wait_halt(e)
    assert await h.reg(e, 0) == 0x7000
    assert await h.pc(e) == p.labels["entry"] + 1


# ------------------------------------------------------------- protocols

UART_CLKDIV = 3                           # 4 clocks per tick, 8 ticks per bit


async def loop_back(w, state):
    """Wire out4 to in3 once state["on"] is set; until then in3 idles high."""
    while True:
        await RisingEdge(w.dut.clk)
        w.set_in(3, w.out(4) if state["on"] else 1)


@cocotb.test()
async def test_uart_between_engines(dut):
    """Engine 0 sends UART frames on out4, engine 1 receives them on in3."""
    w, h = await start(dut)
    link = {"on": False}
    cocotb.start_soon(loop_back(w, link))

    await h.load_file(0, "uart_tx.s")
    await h.load_file(1, "uart_rx.s", entry="start")
    await h.configure(0, clkdiv=UART_CLKDIV, side0="out4")
    await h.configure(1, clkdiv=UART_CLKDIV)
    await h.pins(out={4: 0})
    await h.enable(0b0011)                # both on the same clock edge
    await h.drive(out=[4])
    link["on"] = True

    data = [0x55, 0x00, 0xFF, 0xA7, 0x31, 0x80]
    await h.push(0, data)
    assert await h.wait_rx(1, len(data)) == data
    assert await h.read1(FLAGS) == 0, "receiver reported a framing error"


@cocotb.test()
async def test_four_protocols_at_once(dut):
    """All four engines busy at the same time: UART out, UART in, an SPI
    controller and an I2C controller, each on its own pins, while the host
    keeps talking to the chip."""
    w, h = await start(dut)
    link = {"on": False}
    cocotb.start_soon(loop_back(w, link))
    w.pull(3, True)                       # pull-down on the SPI clock line

    await h.load_file(0, "uart_tx.s")
    await h.load_file(1, "uart_rx.s", entry="start")
    await h.load_file(2, "spi_controller.s")
    i2c = await h.load_file(3, "i2c_controller.s")
    L = i2c.labels
    await h.configure(0, clkdiv=UART_CLKDIV, side0="out4")
    await h.configure(1, clkdiv=UART_CLKDIV)
    await h.configure(2, clkdiv=2, out_dir=1, in_dir=1, autopull=1, autopush=1, side0="io3")
    await h.configure(3, clkdiv=9, out_dir=1, in_dir=1, side0="io6")
    await h.pins(out={4: 0}, io={1: 2, 2: 2, 3: 2, 6: 3, 7: 3}, open_drain=[6, 7])
    await h.enable(0b1111)
    await h.drive(out=[4], io=[1, 2, 3, 6, 7])
    link["on"] = True

    spi_sent = [0xA5, 0x3C, 0x00, 0xFF]
    spi_reply = [0x5A, 0xC3, 0xFF, 0x00]
    spi_seen = []
    spi_task = cocotb.start_soon(spi_target(w, spi_reply, spi_seen))
    device = I2CTargetModel(w, 0x50)
    cocotb.start_soon(device.run())

    uart_data = [0x12, 0x34, 0x56, 0x78, 0x9A]
    await h.push(3, [L["start"], L["write"], 0xA0, L["write"], 0x10,
                     L["write"], 0xDE, L["write"], 0xAD, L["stop"]])
    await h.push(0, uart_data)
    await h.push(2, spi_sent)

    assert await h.wait_rx(1, len(uart_data)) == uart_data
    assert await h.wait_rx(2, len(spi_sent)) == spi_reply
    await spi_task
    assert spi_seen == spi_sent
    assert await h.wait_rx(3, 4) == [0, 0, 0, 0], "an I2C byte was not acknowledged"
    await ClockCycles(dut.clk, 400)
    assert device.mem == {0x10: 0xDE, 0x11: 0xAD}

    # Read the two bytes back over I2C with a repeated start.
    await h.push(3, [L["start"], L["write"], 0xA0, L["write"], 0x10,
                     L["start"], L["write"], 0xA1,
                     L["read"], L["ack"], L["read"], L["nack"], L["stop"]])
    assert await h.wait_rx(3, 5) == [0, 0, 0, 0xDE, 0xAD]
    for e in range(4):
        assert not await h.status(e) & (ST_HALTED | ST_ILLEGAL)


# ------------------------------------------------------ flags, attention

@cocotb.test()
async def test_flags_and_attention(dut):
    """Shared flags between engines and the host, and the attention line."""
    w, h = await start(dut)
    await h.load(0, """
            irq wait 1            ; raise flag 1, wait for the host to clear it
            halt
    """)
    await h.load(1, """
            wait flag 2, 1        ; wait for the host
            irq clear 2
            irq set 5             ; pass it on to engine 2
            halt
    """)
    await h.load(2, """
            wait flag 5, 1
            halt
    """)
    await h.write(ATTN_MASK, 0x02)        # flag 1 raises attention
    await h.write(CTRL, 0x01)             # out0 is the attention line
    await ClockCycles(dut.clk, 4)
    assert w.out(0) == 0

    await h.enable(0b0111)
    await ClockCycles(dut.clk, 10)
    assert w.out(0) == 1, "attention line did not rise"
    assert await h.read1(FLAGS) == 0x02
    assert await h.read1(STATUS) == 0x70  # three engines waiting, none halted
    assert await h.status(0) == ST_RUNNING | ST_STALLED | ST_TX_EMPTY | ST_RX_EMPTY

    await h.write(FLAGS_CLR, 0x02)
    await ClockCycles(dut.clk, 10)
    assert w.out(0) == 0
    assert await h.status(0) & ST_HALTED
    assert await h.read1(FLAGS) == 0x00

    await h.write(ATTN_MASK, 0x10)        # engine 0 halted raises attention
    await ClockCycles(dut.clk, 4)
    assert w.out(0) == 1
    await h.write(ATTN_MASK, 0x20)        # engine 1 halted: not yet
    await ClockCycles(dut.clk, 4)
    assert w.out(0) == 0

    await h.write(FLAGS_SET, 0x04)
    await ClockCycles(dut.clk, 10)
    assert w.out(0) == 1
    assert await h.read1(FLAGS) == 0x20   # flag 2 cleared by engine 1, flag 5 set
    assert await h.read1(STATUS) == 0x07

    await h.write(CTRL, 0x00)             # out0 is an ordinary pin again
    await ClockCycles(dut.clk, 4)
    assert w.out(0) == 0


# ------------------------------------------------------------------ pins

COPY_PINS = """
loop:   tbit pin in1, 1
        ift set pin out1, 1
        ifn set pin out1, 0
        tbit pin in2, 1
        ift set pin out2, 1
        ifn set pin out2, 0
        tbit pin in0, 1
        ift set pin out3, 1
        ifn set pin out3, 0
        jmp loop
"""


@cocotb.test()
async def test_borrowed_pins_and_lock(dut):
    """in1 and in2 are frozen for the engines while the host uses them, and
    the lock bit hands all three host pins to the engines."""
    w, h = await start(dut)
    await h.load(0, COPY_PINS)
    await h.pins(out={1: 0, 2: 0, 3: 0})
    await h.enable(1)
    await h.drive(out=[1, 2, 3])

    w.set_in(1, 1)
    w.set_in(2, 0)
    await ClockCycles(dut.clk, 40)
    assert (w.out(1), w.out(2), w.out(3)) == (1, 0, 1)

    # A transfer wiggles in1 and in2. The engine must not see it.
    seen = set()
    watching = {"on": True}

    async def watch():
        while watching["on"]:
            await RisingEdge(dut.clk)
            seen.add((w.out(1), w.out(2)))

    task = cocotb.start_soon(watch())
    assert await h.read(ID, 2) == [0x4A, 0x01]
    await h.write(dmem(0), [0x55, 0xAA, 0x0F])
    watching["on"] = False
    await task
    assert seen == {(1, 0)}, f"engine saw the host's SPI traffic: {seen}"

    w.set_in(1, 0)
    w.set_in(2, 1)
    await ClockCycles(dut.clk, 40)
    assert (w.out(1), w.out(2), w.out(3)) == (0, 1, 1)

    # Lock: host select is now just in0, and the link is closed.
    await h.write(CTRL, 0x02)
    assert await h.read1(ID) != 0x4A
    w.set_in(0, 0)
    w.set_in(1, 1)
    w.set_in(2, 0)
    await ClockCycles(dut.clk, 40)
    assert (w.out(1), w.out(2), w.out(3)) == (1, 0, 0)
    w.set_in(0, 1)
    await ClockCycles(dut.clk, 40)
    assert w.out(3) == 1


@cocotb.test()
async def test_pin_sharing(dut):
    """OWNER, DRIVE and OPEN_DRAIN decide what reaches a pin."""
    w, h = await start(dut)
    await h.load(0, """
            set pin out5, 1
            set pin io4, 1
            set dir io4, 1
            set pin io5, 0
            halt
    """)
    await h.load(1, """
            set pin out5, 0
            set pin io4, 0
            set pin io5, 1
            halt
    """)
    await h.enable(0b0011)
    await h.wait_halt(0)
    await h.wait_halt(1)
    await h.write(OPEN_DRAIN, 1 << 5)

    async def lines(owner, drive, ext4=1, ext5=1):
        """Set owner and drive for out5, io4, io5; return the three levels."""
        w.pull(4, not ext4)
        w.pull(5, not ext5)
        await h.pins(out={5: owner}, io={4: owner, 5: owner}, open_drain=[5])
        await h.drive(out=[5] if drive else [], io=[4, 5] if drive else [])
        await ClockCycles(dut.clk, 4)
        return w.out(5), w.io(4), w.io(5)

    # Nothing driven: the output is low, the lines follow the outside world.
    assert await lines(0, False) == (0, 1, 1)
    assert await lines(0, False, ext4=0, ext5=0) == (0, 0, 0)
    # Engine 0: out5 high, io4 driven high against the outside, io5 pulled low.
    assert await lines(0, True, ext4=0, ext5=1) == (1, 1, 0)
    # Engine 1: out5 low, io4 is an input, io5 (open-drain, level 1) released.
    assert await lines(1, True, ext4=0, ext5=1) == (0, 0, 1)
    assert await lines(1, True, ext4=1, ext5=0) == (0, 1, 0)
    # Engine 3 has not run: level 0, direction input; open-drain level 0 pulls low.
    assert await lines(3, True, ext4=1, ext5=1) == (0, 1, 0)
    assert await h.read(DRIVE_OUT, 3) == [1 << 5, 0x30, 1 << 5]


@cocotb.test()
async def test_pin_round_trip(dut):
    """How long an engine takes to see a pin it has just written: one clock
    for the output flip-flop, two for the input synchronizer, and the write
    itself takes effect at the end of its tick. Four clocks in all."""
    w, h = await start(dut)
    await h.load(0, """
            set dir io0, 1
            set pin io0, 0
            nop                [7]
            set pin io0, 1
            in pin io0, 1         ; 1 clock after the write
            in pin io0, 1
            in pin io0, 1
            in pin io0, 1         ; 4 clocks after: first to see the new level
            in pin io0, 1
            in pin io0, 1
            in pin io0, 1
            in pin io0, 1
            mov r0, isr
            halt
    """)
    await h.configure(0, clkdiv=0, in_dir=0)          # one clock per tick, first bit ends in bit 0
    await h.pins(io={0: 0})
    await h.drive(io=[0])
    await h.enable(1)
    await h.wait_halt(0)
    assert await h.reg(0, 0) == 0b11111000


@cocotb.test()
async def test_illegal_instruction(dut):
    """A word with condition field 11 stops the engine and is reported."""
    w, h = await start(dut)
    e = 3
    p = await h.load(e, """
            set r0, 7
            nop
            set r0, 9
            halt
    """)
    bad = p.words[1] | (3 << 26)
    await h.write(prog(e, 1), [(bad >> s) & 0xFF for s in (0, 8, 16, 24)])
    await h.enable(1 << e)
    st = await h.wait_halt(e)
    assert st & ST_ILLEGAL
    assert await h.pc(e) == 1
    assert await h.reg(e, 0) == 7
    await h.enable(0)
    await h.restart(1 << e)
    assert await h.status(e) == ST_TX_EMPTY | ST_RX_EMPTY
