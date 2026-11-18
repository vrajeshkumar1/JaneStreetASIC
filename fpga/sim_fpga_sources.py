#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
"""Run the whole-chip tests (test/test.py) on the sources the FPGA build
uses: pe_fifo.sv without its latch modules, fpga/pe_lmem_ff.sv and
fpga/fpga_ram.v. This checks the FPGA stand-ins behave like the chip's parts.

    python fpga/sim_fpga_sources.py [test name filter]
"""

import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GEN = os.path.join(ROOT, "fpga", "build", "sim_src")


def strip(text, module):
    new, n = re.subn(r"module %s\b.*?\nendmodule\n" % module, "", text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"module {module} not found in pe_fifo.sv")
    return new


def main():
    os.makedirs(GEN, exist_ok=True)
    for name in ("project.sv", "pe_pins.sv", "pe_spi.sv", "pe_regs.sv", "pe_engine.sv"):
        shutil.copy(os.path.join(ROOT, "src", name), GEN)
    text = open(os.path.join(ROOT, "src", "pe_fifo.sv")).read()
    for m in ("pe_clkgate", "pe_lmem"):
        text = strip(text, m)
    open(os.path.join(GEN, "pe_fifo.sv"), "w").write(text)
    shutil.copy(os.path.join(ROOT, "fpga", "pe_lmem_ff.sv"), GEN)
    shutil.copy(os.path.join(ROOT, "fpga", "fpga_ram.v"), GEN)
    sources = "project.sv pe_pins.sv pe_spi.sv pe_regs.sv pe_engine.sv pe_fifo.sv pe_lmem_ff.sv fpga_ram.v"
    cmd = ["make", "-B", f"SRC_DIR={GEN}", f"PROJECT_SOURCES={sources}", "SRAM_MODELS=",
           "SIM_BUILD=sim_build/fpga"]
    env = dict(os.environ)
    if len(sys.argv) > 1:
        env["COCOTB_TEST_FILTER"] = sys.argv[1]
    return subprocess.call(cmd, cwd=os.path.join(ROOT, "test"), env=env)


if __name__ == "__main__":
    sys.exit(main())
