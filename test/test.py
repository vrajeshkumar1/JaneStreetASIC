# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
#
# Test for the PROBE build (src/project.sv). It checks the memory block's
# interface as the engine will use it: write, read back one clock later, hold,
# and the "follow the program" loop where the next address is computed from the
# word that just came out of the memory.

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

CMD_IDLE, CMD_ADDR, CMD_SHIFT, CMD_WRITE, CMD_READ, CMD_SEL, CMD_RUN = range(7)

CLOCK_NS = 16.666  # 60 MHz


async def cmd(dut, code, data=0, cycles=1):
    """Drive one command for `cycles` clocks, then return to idle."""
    await FallingEdge(dut.clk)
    dut.uio_in.value = code
    dut.ui_in.value = data
    await ClockCycles(dut.clk, cycles)
    await FallingEdge(dut.clk)
    dut.uio_in.value = CMD_IDLE
    dut.ui_in.value = 0


async def write_word(dut, addr, word):
    await cmd(dut, CMD_ADDR, addr)
    for shift in (24, 16, 8, 0):
        await cmd(dut, CMD_SHIFT, (word >> shift) & 0xFF)
    await cmd(dut, CMD_WRITE)


async def read_word(dut, addr):
    await cmd(dut, CMD_ADDR, addr)
    await cmd(dut, CMD_READ)
    word = 0
    for sel in range(4):
        await cmd(dut, CMD_SEL, sel)
        await ClockCycles(dut.clk, 4)  # synchronizer + output register
        word |= int(dut.uo_out.value) << (8 * sel)
    return word


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, CLOCK_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


@cocotb.test()
async def test_write_read(dut):
    """Write a pattern to several addresses and read every byte back."""
    await start(dut)
    assert int(dut.uio_oe.value) == 0, "probe must leave the bidirectional pins as inputs"

    words = {0x00: 0xDEADBEEF, 0x01: 0x01234567, 0x7F: 0xA5A5A5A5, 0xFF: 0x89ABCDEF}
    for addr, word in words.items():
        await write_word(dut, addr, word)
    for addr, word in words.items():
        got = await read_word(dut, addr)
        assert got == word, f"addr {addr:#04x}: read {got:#010x}, expected {word:#010x}"

    # Overwrite one word and confirm the neighbours kept their value.
    await write_word(dut, 0x01, 0xFFFF0000)
    assert await read_word(dut, 0x01) == 0xFFFF0000
    assert await read_word(dut, 0x00) == 0xDEADBEEF
    assert await read_word(dut, 0x7F) == 0xA5A5A5A5


@cocotb.test()
async def test_run_loop(dut):
    """Follow a small program: the next address comes from the word just read."""
    await start(dut)

    # Word format used by the probe's RUN mode:
    #   [31:28] == 0     -> jump
    #   [27:26] == 00    -> always;  otherwise taken when bit 27 differs from T
    #   [7:0]            -> jump target
    #   bit 0 of every word executed becomes the new T flag
    JMP = lambda target: target & 0xFF            # always
    JMP_IF_T0 = lambda target: (0b10 << 26) | (target & 0xFF)  # taken when T == 0
    NOP = lambda t=0: (0x1 << 28) | (t & 1)       # not a jump; sets T

    program = {
        0x10: NOP(0),          # T <- 0
        0x11: NOP(1),          # T <- 1
        0x12: JMP(0x20),       # always -> 0x20   (target is even, so T <- 0)
        0x20: NOP(0),          # T <- 0
        0x21: JMP_IF_T0(0x31), # T == 0 -> taken -> 0x31  (target odd, T <- 1)
        0x31: JMP_IF_T0(0x10), # T == 1 -> not taken -> 0x32 (T <- 0)
        0x32: JMP(0x10),       # back to the start
    }
    for addr, word in program.items():
        await write_word(dut, addr, word)

    expected = [0x10, 0x11, 0x12, 0x20, 0x21, 0x31, 0x32, 0x10, 0x11, 0x12, 0x20]

    await cmd(dut, CMD_ADDR, 0x10)
    await FallingEdge(dut.clk)
    dut.uio_in.value = CMD_RUN
    seen = []
    for _ in range(len(expected) + 8):
        await FallingEdge(dut.clk)
        seen.append(int(dut.uo_out.value))
    dut.uio_in.value = CMD_IDLE

    # Drop the clocks before the first program counter value appears.
    first = seen.index(0x10)
    trace = seen[first:first + len(expected)]
    assert trace == expected, f"program counter trace {[hex(v) for v in trace]}"
