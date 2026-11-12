#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
"""Run the engine tests:  python test/engine/run.py
Needs Icarus Verilog and the packages in test/requirements.txt."""

import os
import sys
from pathlib import Path

from cocotb_tools.runner import get_runner

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def main():
    sources = [
        ROOT / "src" / "pe_fifo.sv",
        ROOT / "src" / "pe_engine.sv",
        ROOT / "test" / "ihp_sram" / "RM_IHPSG13_1P_core_behavioral_bm_bist.v",
        ROOT / "test" / "ihp_sram" / "RM_IHPSG13_1P_256x32_c2_bm_bist.v",
        HERE / "tb_engine.sv",
    ]
    runner = get_runner(os.environ.get("SIM", "icarus"))
    runner.build(
        sources=sources,
        hdl_toplevel="tb_engine",
        defines={"SIM": 1, "FUNCTIONAL": 1},
        build_dir=HERE / "sim_build",
        always=True,
        timescale=("1ns", "1ps"),
    )
    results = runner.test(
        hdl_toplevel="tb_engine",
        test_module=os.environ.get("MODS", "test_isa,test_protocols").split(","),
        test_dir=HERE,
        build_dir=HERE / "sim_build",
    )
    from cocotb_tools.check_results import get_results
    total, failed = get_results(results)
    print(f"{total} tests, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
