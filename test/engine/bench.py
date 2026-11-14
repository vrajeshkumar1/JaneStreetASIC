# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
"""Helpers shared by the engine tests: reset, program loading, settings and
the host-side FIFO, register and data-memory access of tb_engine.sv."""

import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from pasm import assemble  # noqa: E402

CLOCK_NS = 16.666  # 60 MHz


def pin(name):
    """Pin number as the settings registers use it for writing."""
    kind, n = name[:-1], int(name[-1])
    return {"out": 0, "io": 8}[kind] + n


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.labels = {}

    async def reset(self):
        d = self.dut
        cocotb.start_soon(Clock(d.clk, CLOCK_NS, unit="ns").start())
        for name in ("enable", "restart", "cfg_out_dir", "cfg_in_dir", "cfg_autopull",
                     "cfg_autopush", "cfg_side0", "cfg_side1", "cfg_crc_dir",
                     "cfg_crc_poly", "cfg_open_drain", "h_prog_we", "h_prog_addr",
                     "h_prog_wdata", "h_tx_push", "h_tx_data", "h_rx_pop", "h_dm_we",
                     "h_dm_addr", "h_dm_wdata", "h_reg_we", "h_reg_sel", "h_reg_hi", "h_reg_wdata",
                     "h_pc_we", "h_pc_wdata", "h_flag_set", "h_flag_clr", "cfg_clkdiv"):
            getattr(d, name).value = 0
        d.cfg_pull_thresh.value = 8
        d.cfg_push_thresh.value = 8
        d.cfg_crc_width.value = 32
        d.ui_in.value = 0xFF
        d.io_ext.value = 0xFF
        d.rst_n.value = 0
        await ClockCycles(d.clk, 5)
        d.rst_n.value = 1
        await ClockCycles(d.clk, 3)

    # ------------------------------------------------------------ program
    async def load(self, source, entry=None):
        """Assemble and load a program. Returns the Program."""
        prog = assemble(source)
        d = self.dut
        for addr, word in enumerate(prog.words):
            await FallingEdge(d.clk)
            d.h_prog_we.value = 1
            d.h_prog_addr.value = addr
            d.h_prog_wdata.value = word
        await FallingEdge(d.clk)
        d.h_prog_we.value = 0
        self.labels = prog.labels
        if entry is not None:
            d.h_pc_we.value = 1
            d.h_pc_wdata.value = prog.labels[entry]
            await FallingEdge(d.clk)
            d.h_pc_we.value = 0
        return prog

    async def load_file(self, name, entry=None):
        with open(os.path.join(ROOT, "programs", name)) as f:
            return await self.load(f.read(), entry)

    def settings(self, **kw):
        """clkdiv, out_dir, in_dir, autopull, autopush, pull_thresh, push_thresh,
        side0, side1 (pin names), side0_dir, open_drain (list of io pin names),
        crc_dir, crc_poly, crc_width."""
        d = self.dut
        for key in ("clkdiv", "out_dir", "in_dir", "autopull", "autopush",
                    "pull_thresh", "push_thresh", "crc_dir", "crc_poly", "crc_width"):
            if key in kw:
                getattr(d, "cfg_" + key).value = kw[key]
        for key in ("side0", "side1"):
            if key in kw:
                getattr(d, "cfg_" + key).value = 0x10 | pin(kw[key]) | (0x20 if kw.get(key + "_dir") else 0)
        if "open_drain" in kw:
            mask = 0
            for name in kw["open_drain"]:
                mask |= 1 << int(name[-1])
            d.cfg_open_drain.value = mask

    async def start(self):
        await FallingEdge(self.dut.clk)
        self.dut.enable.value = 1

    async def stop(self):
        await FallingEdge(self.dut.clk)
        self.dut.enable.value = 0

    # --------------------------------------------------------------- host
    async def push(self, byte):
        d = self.dut
        await FallingEdge(d.clk)
        assert not d.tx_full.value, "TX FIFO full"
        d.h_tx_push.value = 1
        d.h_tx_data.value = byte
        await FallingEdge(d.clk)
        d.h_tx_push.value = 0

    async def pop(self, timeout_clocks=200000):
        d = self.dut
        for _ in range(timeout_clocks):
            await FallingEdge(d.clk)
            if not d.rx_empty.value:
                value = int(d.rx_data.value)
                d.h_rx_pop.value = 1
                await FallingEdge(d.clk)
                d.h_rx_pop.value = 0
                return value
        raise AssertionError("no byte arrived in the RX FIFO")

    async def reg(self, n):
        d = self.dut
        await FallingEdge(d.clk)
        d.h_reg_sel.value = n
        await FallingEdge(d.clk)
        return int(d.reg_rdata.value)

    async def set_reg(self, n, value):
        d = self.dut
        await FallingEdge(d.clk)
        # The host writes a register one byte at a time.
        d.h_reg_sel.value = n
        for hi in (0, 1):
            d.h_reg_hi.value = hi
            d.h_reg_wdata.value = (value >> (8 * hi)) & 0xFF
            d.h_reg_we.value = 1
            await FallingEdge(d.clk)
        d.h_reg_we.value = 0

    async def dm_write(self, addr, value):
        d = self.dut
        await FallingEdge(d.clk)
        d.h_dm_addr.value = addr
        d.h_dm_wdata.value = value
        d.h_dm_we.value = 1
        await FallingEdge(d.clk)
        d.h_dm_we.value = 0

    async def dm_read(self, addr):
        d = self.dut
        await FallingEdge(d.clk)
        d.h_dm_addr.value = addr
        await FallingEdge(d.clk)
        return int(d.dm_rdata.value)

    async def wait_halt(self, timeout_clocks=20000):
        d = self.dut
        for _ in range(timeout_clocks):
            await RisingEdge(d.clk)
            if d.halted.value:
                return
        raise AssertionError("engine did not halt")

    async def run(self, source, **settings):
        """Load a program that ends in halt, run it, return when it halts."""
        await self.reset()
        await self.load(source)
        self.settings(**settings)
        await self.start()
        await self.wait_halt()
        assert not self.dut.illegal.value, "engine stopped on an illegal instruction"
