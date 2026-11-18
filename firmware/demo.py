# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: Apache-2.0
"""First checks on real hardware: the Tiny Tapeout demo board, or a
MicroPython board wired to the PYNQ-Z2 build (fpga/README.md). Copy
pe_host.py, programs.py and this file to the board, then

    import demo
    chip = demo.run()                    # demo board
    chip = demo.run(PinLink(...))        # other boards, see pe_host.py

On the demo board, select the design and start its clock first:

    from ttboard.demoboard import DemoBoard
    tt = DemoBoard.get()
    tt.shuttle.tt_um_vrajeshkumar1_janestreetasic.enable()
    tt.clock_project_PWM(60_000_000)

The protocol programs assume a 60 MHz clock; the self-test runs at any
clock rate.
"""

from pe_host import Chip, TTBoardLink, ST_HALTED

SIZES = {0: (256, 8, 4, False, False), 1: (256, 8, 4, False, False),
         2: (512, 8, 4, True, True), 3: (256, 16, 16, True, True)}


def selftest(chip, programs):
    """The link, the size and feature registers, every engine running a
    short program (programs["selftest"]: r0 = 3 * r1, sent back through the
    RX FIFO), and the shared flags."""
    assert chip.check(), "no answer from the chip (ID register)"
    for e in range(4):
        got = chip.sizes(e)
        assert got == SIZES[e], "engine %d sizes %r" % (e, got)
    chip.enable(0)
    for e in range(4):
        chip.restart(1 << e)
        chip.load(e, programs["selftest"])
        chip.set_reg(e, 1, 10 + e)
        chip.start(e)
        got = chip.collect(e, 1)
        assert got == [3 * (10 + e)], "engine %d sent %r" % (e, got)
        assert chip.status(e) & ST_HALTED, "engine %d did not halt" % e
        chip.stop(e)
    chip.set_flags(0x81)
    assert chip.flags() == 0x81
    chip.clear_flags(0xFF)
    assert chip.flags() == 0


def run(link=None):
    from programs import PROGRAMS
    chip = Chip(link or TTBoardLink())
    selftest(chip, PROGRAMS)
    print("link, sizes, engines and flags: ok")
    return chip
