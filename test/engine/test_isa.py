# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
"""Instruction-level tests for one engine (docs/spec.md, part 1)."""

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

from bench import Bench


@cocotb.test()
async def test_alu(dut):
    """set, add, sub, and, or, xor, shl, shr with register and immediate operands."""
    b = Bench(dut)
    await b.run("""
        set r0, 0x1234
        set r1, 0x00F0
        add r2, r0, r1        ; 0x1324
        sub r3, r0, r1        ; 0x1144
        and r4, r0, r1        ; 0x0030
        or  r5, r0, r1        ; 0x12F4
        xor r6, r0, r1        ; 0x12C4
        add r7, r0, 1000      ; 0x161C
        halt
    """)
    assert [await b.reg(n) for n in range(2, 8)] == [0x1324, 0x1144, 0x0030, 0x12F4, 0x12C4, 0x161C]

    await b.run("""
        set r0, 0x8001
        shl r1, r0, 3         ; 0x0008
        shr r2, r0, 15        ; 0x0001
        set r3, 4
        shl r4, r0, r3        ; 0x0010
        shr r5, r0, r3        ; 0x0800
        sub r6, r3, 5         ; wraps to 0xFFFF
        halt
    """)
    assert [await b.reg(n) for n in (1, 2, 4, 5, 6)] == [0x0008, 0x0001, 0x0010, 0x0800, 0xFFFF]


@cocotb.test()
async def test_jumps(dut):
    """cmp with eq/ne/lt/ge, the register tests, and a counted loop."""
    b = Bench(dut)
    await b.run("""
        set r0, 5
        set r7, 0
        cmp r0, 5
        jmp ne, bad
        jmp lt, bad
        jmp eq, a
        jmp bad
a:      add r7, r7, 1         ; 1
        cmp r0, 9
        jmp ge, bad
        jmp eq, bad
        jmp lt, b
        jmp bad
b:      add r7, r7, 1         ; 2
        set r1, 9
        cmp r1, r0
        jmp ge, c
        jmp bad
c:      add r7, r7, 1         ; 3
        set r2, 0
        jmp r2, bad           ; r2 is zero: not taken
        jmp !r2, d
        jmp bad
d:      add r7, r7, 1         ; 4
        set r3, 4
        set r4, 0
loop:   add r4, r4, 1         ; runs 5 times: r3 = 4, 3, 2, 1, 0
        jmp r3--, loop
        halt
bad:    set r7, 0xDEAD
        halt
    """)
    assert await b.reg(7) == 4
    assert await b.reg(4) == 5
    assert await b.reg(3) == 0xFFFF   # decremented once more on the final, untaken test


@cocotb.test()
async def test_call_ret_and_computed_jump(dut):
    """call, ret, saving lr for a second level, and mov pc."""
    b = Bench(dut)
    await b.run("""
        set r0, 0
        call one
        call two
        set r5, there
        mov pc, r5
        set r0, 0xBAD
there:  add r0, r0, 0x100
        halt
one:    add r0, r0, 1
        ret
two:    mov r6, lr            ; keep the return address
        call one              ; overwrites lr
        add r0, r0, 0x10
        mov pc, r6
    """)
    assert await b.reg(0) == 0x112


@cocotb.test()
async def test_data_memory(dut):
    """ld and st with base, base + offset and absolute addresses; host access."""
    b = Bench(dut)
    await b.reset()
    await b.dm_write(3, 0x5A)
    await b.load("""
        set r0, 0xABCD
        st r0, [@0]           ; low byte only: 0xCD
        set r1, 4
        st r1, [r1]           ; memory[4] = 4
        st r0, [r1+7]         ; memory[11] = 0xCD
        ld r2, [@3]           ; written by the host: 0x5A
        ld r3, [r1+7]
        set r4, 14
        st r1, [r4+3]         ; address wraps: memory[1] = 4
        ld r5, [@1]
        halt
    """)
    await b.start()
    await b.wait_halt()
    assert await b.reg(2) == 0x5A
    assert await b.reg(3) == 0xCD
    assert await b.reg(5) == 4
    assert await b.dm_read(0) == 0xCD
    assert await b.dm_read(4) == 4
    assert await b.dm_read(11) == 0xCD


@cocotb.test()
async def test_mov_and_conditions(dut):
    """mov inv / rev / par, tst, tbit, and ift / ifn."""
    b = Bench(dut)
    await b.run("""
        set r0, 0x00B1        ; 1011 0001: four ones, even parity
        mov r1, r0, inv       ; 0xFF4E
        mov r2, r0, rev       ; 0x008D
        par r0                ; T = 0
        ift set r3, 1         ; skipped
        ifn set r3, 2         ; runs
        set r4, 0x0007        ; three ones
        par r4                ; T = 1
        ift set r5, 1         ; runs
        ifn set r5, 2         ; skipped
        tbit r0.4, 1          ; bit 4 of 0xB1 is 1: T = 1
        ift set r6, 0x11
        tbit r0.1, 1          ; bit 1 is 0: T = 0
        ift set r6, 0x22      ; skipped
        cmp r4, 7
        tst eq                ; T = 1
        ift add r6, r6, 1     ; 0x12
        tst ne                ; T = 0
        ift add r6, r6, 1     ; skipped
        halt
    """)
    assert [await b.reg(n) for n in (1, 2, 3, 5, 6)] == [0xFF4E, 0x008D, 2, 1, 0x12]


@cocotb.test()
async def test_shift_registers(dut):
    """pull / out to registers and in / push, in both bit orders."""
    b = Bench(dut)
    src = """
        pull
        out r0, 3
        out r1, 5
        in r0, 3
        in r1, 5
        push
        halt
    """
    # Lowest bit first: 0xB5 = 10110 101 -> the first 3 bits out are 101, then 10110.
    await b.reset()
    await b.load(src)
    await b.push(0xB5)
    await b.start()
    await b.wait_halt()
    assert (await b.reg(0), await b.reg(1)) == (0b101, 0b10110)
    assert await b.pop() == 0xB5

    # Highest bit first: 0xB5 = 101 10101 -> the first 3 bits out are 101, then 10101.
    await b.reset()
    await b.load(src)
    b.settings(out_dir=1, in_dir=1)
    await b.push(0xB5)
    await b.start()
    await b.wait_halt()
    assert (await b.reg(0), await b.reg(1)) == (0b101, 0b10101)
    assert await b.pop() == 0xB5


@cocotb.test()
async def test_fifo_flow(dut):
    """Blocking pull waits for the host; non-blocking pull sets the debug bit;
    the FIFO tests see the levels."""
    b = Bench(dut)
    await b.reset()
    await b.load("""
        pull noblock          ; FIFO empty: nothing loaded, debug bit 0 set
        tst txempty
        ift set r0, 1
        pull                  ; stalls until the host pushes
        mov r1, osr
        mov isr, r1
        push
        halt
    """)
    await b.start()
    await ClockCycles(dut.clk, 20)
    assert dut.stalled.value == 1 and dut.halted.value == 0
    assert int(dut.debug.value) & 1
    await b.push(0x3C)
    await b.wait_halt()
    assert await b.reg(0) == 1
    assert await b.pop() == 0x3C


def crc_ref(data_bits, poly, width, left, init=0):
    crc = init
    for bit in data_bits:
        if left:
            fb = ((crc >> (width - 1)) & 1) ^ bit
            crc = (crc << 1) & ((1 << width) - 1)
        else:
            fb = (crc & 1) ^ bit
            crc >>= 1
        if fb:
            crc ^= poly
    return crc


@cocotb.test()
async def test_checksum(dut):
    """The checksum unit against a software reference, both directions."""
    b = Bench(dut)
    data = [0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39]   # "123456789"
    src = """
        set r0, 0xFFFF
        mov crc_lo, r0
        set r1, 8             ; nine bytes
byte:   pull
bit:    out null, 1, feed
        jmp !osre, bit
        jmp r1--, byte
        mov r2, crc_lo
        mov r3, crc_hi
        halt
    """
    # CRC-16 as USB uses it: lowest bit first, polynomial 0x8005 reversed = 0xA001.
    await b.reset()
    await b.load(src)
    b.settings(crc_dir=0, crc_poly=0xA001, crc_width=16)
    for byte in data:
        await b.push(byte)
    await b.start()
    await b.wait_halt()
    bits = [(byte >> i) & 1 for byte in data for i in range(8)]
    assert await b.reg(2) == crc_ref(bits, 0xA001, 16, left=False, init=0xFFFF)
    assert await b.reg(2) == 0x4B37     # CRC-16/MODBUS check value for "123456789"

    # CRC-16/CCITT-FALSE: highest bit first, polynomial 0x1021, check value 0x29B1.
    await b.reset()
    await b.load(src)
    b.settings(out_dir=1, crc_dir=1, crc_poly=0x1021, crc_width=16)
    for byte in data:
        await b.push(byte)
    await b.start()
    await b.wait_halt()
    assert await b.reg(2) == 0x29B1
    assert await b.reg(3) == 0

    # CRC-32 as Ethernet uses it: reversed polynomial 0xEDB88320, 32 bits wide.
    await b.reset()
    await b.load(src.replace("mov crc_lo, r0", "mov crc_lo, r0\n        mov crc_hi, r0"))
    b.settings(crc_dir=0, crc_poly=0xEDB88320, crc_width=32)
    for byte in data:
        await b.push(byte)
    await b.start()
    await b.wait_halt()
    crc = (await b.reg(3) << 16) | await b.reg(2)
    assert crc ^ 0xFFFFFFFF == 0xCBF43926   # CRC-32 check value for "123456789"


@cocotb.test()
async def test_wait(dut):
    """wait pin, wait change, timeouts and the recorded wait time."""
    b = Bench(dut)
    await b.reset()
    await b.load("""
        .define A in1
        .define B io2
        set r7, 20
        wait pin A, 0, timeout r7     ; A stays high: times out, T = 1
        ift set r0, 1
        mov r1, wtime                 ; 20
        wait pin A, 0                 ; released by the test
        mov r2, wtime
        wait change A, B              ; B moves
        set r3, 0x33
        wait change A, timeout r7     ; nothing moves: times out
        ift set r4, 0x44
        wait flag 5, 1                ; set by the test
        set r5, 0x55
        halt
    """)
    await b.start()
    await ClockCycles(dut.clk, 40)
    assert await b.reg(0) == 1
    assert await b.reg(1) == 20
    assert dut.stalled.value == 1
    dut.ui_in.value = 0xFD             # in1 low
    await ClockCycles(dut.clk, 10)
    assert await b.reg(2) > 5          # it had been waiting for a while
    assert await b.reg(3) == 0
    dut.io_ext.value = 0xFB            # io2 low
    await ClockCycles(dut.clk, 40)
    assert await b.reg(3) == 0x33
    assert await b.reg(4) == 0x44
    assert dut.halted.value == 0
    await FallingEdge(dut.clk)
    dut.h_flag_set.value = 0x20
    await FallingEdge(dut.clk)
    dut.h_flag_set.value = 0
    await b.wait_halt()
    assert await b.reg(5) == 0x55


@cocotb.test()
async def test_flags_between_engine_and_host(dut):
    """irq set / clear, and irq wait stalling until the host clears the flag."""
    b = Bench(dut)
    await b.reset()
    await b.load("""
        irq set 1
        irq set 2
        irq clear 1
        irq wait 6            ; sets flag 6, stalls until it is cleared
        set r0, 0x77
        halt
    """)
    await b.start()
    await ClockCycles(dut.clk, 20)
    assert int(dut.flags.value) == 0b01000100
    assert dut.halted.value == 0
    await FallingEdge(dut.clk)
    dut.h_flag_clr.value = 0x40
    await FallingEdge(dut.clk)
    dut.h_flag_clr.value = 0
    await b.wait_halt()
    assert await b.reg(0) == 0x77


async def edge_times(dut, signal, bit, count, timeout_clocks=5000):
    """Clock numbers at which a pin changes."""
    times, last, clock = [], (int(signal.value) >> bit) & 1, 0
    while len(times) < count:
        await RisingEdge(dut.clk)
        clock += 1
        assert clock < timeout_clocks, "pin did not toggle"
        now = (int(signal.value) >> bit) & 1
        if now != last:
            times.append(clock)
            last = now
    return times


@cocotb.test()
async def test_timing(dut):
    """One tick per instruction, taken or not; delay adds ticks; the divider
    sets the tick length; a skipped instruction costs the same as a run one."""
    b = Bench(dut)
    src = """
loop:   toggle pin out0            ; edge
        nop
        jmp loop                   ; 3 ticks per edge
    """
    for clkdiv in (0, 1, 4):
        await b.reset()
        await b.load(src)
        b.settings(clkdiv=clkdiv)
        await b.start()
        t = await edge_times(dut, dut.uo_out, 0, 6)
        gaps = {t[i + 1] - t[i] for i in range(len(t) - 1)}
        assert gaps == {3 * (clkdiv + 1)}, f"clkdiv {clkdiv}: gaps {gaps}"

    await b.reset()
    await b.load("""
        set r0, 0
loop:   toggle pin out0     [5]    ; 6 ticks
        tbit r0.0, 1
        ift toggle pin out1 [2]    ; 3 ticks whether it runs or not
        xor r0, r0, 1
        jmp loop                   ; 12 ticks per out0 edge
    """)
    await b.start()
    t = await edge_times(dut, dut.uo_out, 0, 6)
    assert {t[i + 1] - t[i] for i in range(len(t) - 1)} == {12}
    t = await edge_times(dut, dut.uo_out, 1, 4)
    assert {t[i + 1] - t[i] for i in range(len(t) - 1)} == {24}


@cocotb.test()
async def test_side_set_and_pins(dut):
    """Side-set on level and on direction, set pin, set dir, whole-port moves,
    and side-set winning over the instruction on the same pin."""
    b = Bench(dut)
    await b.reset()
    await b.load("""
        set dir io4, 1
        set pin io4, 0
        set r0, 0xA0
        mov pins_out, r0                 ; out7 and out5 high
        set pin out2, 1       side 2     ; side-set: out5 low, io6 becomes an output (level 0)
        set pin out5, 0       side 3 [4] ; the instruction says 0, side-set says 1: out5 high
        mov r1, pins_io                  ; io4 and io6 driven low, the rest pulled up
        mov r2, pins_in
        halt
    """)
    b.settings(side0="out5", side1="io6", side1_dir=1)
    dut.ui_in.value = 0x5A
    await b.start()
    await b.wait_halt()
    await ClockCycles(dut.clk, 2)
    assert int(dut.uo_out.value) == 0xA4
    assert int(dut.pin_dir.value) == 0x50
    assert await b.reg(1) == 0xAF
    assert await b.reg(2) == 0x5A


@cocotb.test()
async def test_halt_and_illegal(dut):
    """halt stops the engine; an illegal word stops it and sets the illegal bit;
    restart clears both."""
    b = Bench(dut)
    await b.run("""
        set r0, 1
        halt
        set r0, 2
    """)
    assert await b.reg(0) == 1
    assert dut.illegal.value == 0

    await b.reset()
    await b.load("set r0, 3\nnop\n")
    # Patch address 1 with a word whose condition field is the illegal value 11.
    await FallingEdge(dut.clk)
    dut.h_prog_we.value = 1
    dut.h_prog_addr.value = 1
    dut.h_prog_wdata.value = 0x6C000000 | (15 << 14) | (15 << 7)
    await FallingEdge(dut.clk)
    dut.h_prog_we.value = 0
    await b.start()
    await b.wait_halt()
    assert dut.illegal.value == 1
    assert int(dut.pc.value) == 1

    await FallingEdge(dut.clk)
    dut.restart.value = 1
    dut.enable.value = 0
    await FallingEdge(dut.clk)
    dut.restart.value = 0
    await ClockCycles(dut.clk, 2)
    assert dut.halted.value == 0 and dut.illegal.value == 0 and int(dut.pc.value) == 0
