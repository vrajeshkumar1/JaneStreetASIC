# Use of AI tools

The competition asks entrants to describe how AI tools were used. This file is
the running record.

## Roles

- **Vrajesh Kumar:** design decisions, review, the UVM testbench, FPGA and board
  bring-up, small edits.
- **Claude (Anthropic), used through the Claude app:** research into the
  process, the cell library and the layout flow; proposals for the architecture
  and instruction set, each accepted, changed or rejected by the owner;
  writing the specification, the RTL, the assembler, the example programs and
  the template's minimal tests.

## Log

| Date | What the AI tool produced | How it was checked |
|---|---|---|
| 11 Nov 2026 | `docs/spec.md` v0.1, `docs/decisions.md`, this file, `README.md`, `docs/info.md`, `NOTICE.md` | Field widths in the instruction formats were added up against the 19 operand bits. Not yet reviewed by the owner |
| 11 Nov 2026 | `programs/*.s` (five draft programs) | Tick counts were worked out by hand. Not assembled, not simulated |
| 11 Nov 2026 | Probe build: `src/project.sv`, `src/sram_bb.v`, `test/test.py`, changes to `test/Makefile`, `test/tb.v`, `info.yaml` | Both tests pass in Icarus Verilog 13.0 with cocotb 2.0.1. Yosys 0.70 synthesizes it with no latches (117 flip-flops, 250 cells). Verilator 5.052 lint reports only the undriven output of the black box |
| 11 Nov 2026 | `src/config.json` changes, `librelane_plugin_jsasic_pdn.py` | The file parses as JSON. The layout flow itself has not been run; the settings are copied from a project that is known to pass it (see `NOTICE.md`) |
