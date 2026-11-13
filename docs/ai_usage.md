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
| 12 Nov 2026 | Probe layout run on GitHub Actions (run by the owner); the AI tool read the timing, power and sign-off reports | Zero layout, netlist-comparison and antenna errors; slack figures recorded in `docs/decisions.md` |
| 12 Nov 2026 | `src/pe_engine.sv`, `src/pe_fifo.sv` (one engine), `tools/pasm.py` (assembler), `test/engine/*` (test bench, 13 instruction tests, 5 protocol tests with bus models) | All 18 tests pass in Icarus Verilog 13.0. Yosys 0.70 synthesizes the engine with the CMOS5L cell library (no latches, 93,871 um2). Verilator lint is clean. The engine has not been through the layout flow |
| 12 Nov 2026 | Changes to `programs/*.s` (pin setup lines; I2C controller delays) and `docs/spec.md` v0.2 | The programs are the ones the protocol tests run |
| 12 Nov 2026 | Host interface and top level: `src/pe_spi.sv`, `src/pe_regs.sv`, `src/pe_pins.sv`, new `src/project.sv` (four engines, four memory blocks, replacing the probe); `src/config.json` for four memory blocks | Verilator 5.052 lint is clean. Yosys 0.70 synthesizes the design with the CMOS5L cell library: 0.414 mm2 of cells, 3,259 flip-flops, no latches |
| 12 Nov 2026 | Whole-chip tests: `test/test.py` (12 tests), `test/host.py` (SPI host model), `test/models.py` (UART, SPI and I2C models, shared with the engine tests), `test/tb.v` | All 12 pass in Icarus Verilog 13.0, and the 18 engine tests still pass. Eight deliberate faults were put into the design one at a time (for example: pins not frozen during a host transfer, lock bit ignored, program writes allowed while running); each made at least one test fail. One test found a real fault (a clock pin rising as host select fell was counted as a clock edge), which was then fixed. The tests also pass on the gate-level netlist from Yosys |
| 12 Nov 2026 | Operand fields of nine instructions moved so that register and pin numbers are in fixed bits (`src/pe_engine.sv`, `tools/pasm.py`, `docs/spec.md` v0.3) | The 30 tests pass unchanged, since they go through the assembler. Effect on timing measured with a trial placement (below) |
| 12 Nov 2026 | Trial placement and global route in the AI tool's workspace with OpenROAD 26Q3 and the PDK's timing libraries, to estimate timing and routing before the real run | Figures in `docs/decisions.md`. This is not the Tiny Tapeout flow: no power grid, no detailed route, different synthesis script. The real layout run has not been done for this design |
| 13 Nov 2026 | Diagnosis of the failed four-engine layout run from its logs; `src/config.json` changed (area-oriented synthesis, routability-driven placement off, detailed routing capped at 12 passes); FIFO depth and data memory size made parameters of the engine (no change in behaviour at the present sizes) | The real flow (LibreLane 3.1.0.dev4, the version the GitHub run used, and the same PDK version) was installed in the AI tool's workspace and run on the delivered files up to the clock tree stage; detailed routing was run to the end only for a one-engine version. The 30 simulation tests pass. The full flow for four engines has not been run to the end anywhere yet |
| 13 Nov 2026 | Unequal engines: per-engine sizes in `src/project.sv`, `ldm` / `stm` in `src/pe_engine.sv` and `tools/pasm.py`, 512-word block for engine 2 (`src/sram_bb.v`, `src/config.json`, `test/ihp_sram/`), host map and registers in `src/pe_regs.sv`, `.org` in the assembler, `docs/spec.md` v0.4 | 14 whole-chip tests and 19 engine tests pass in simulation, including new ones for `ldm` / `stm` (values, neighbours untouched, timing), code above word 255 on engine 2, and both FIFO depths. Verilator lint clean. Layout: see `docs/decisions.md`; detailed routing has not been run by the AI tool |
