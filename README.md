![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# ProtocolEmulatorASIC

A programmable protocol emulator for the Jane Street protocol emulator ASIC
competition, targeting an 8x4 Tiny Tapeout tile on IHP CMOS5L.

The chip holds four small processors ("engines"). Each runs a short program
that reads pins, writes pins and counts time precisely enough to speak a serial
protocol. UART, SPI, I2C, a low-speed USB device and a 10BASE-T Ethernet
transmitter are written as programs; none of them is built into the hardware.
`docs/writeup.md` describes the design and how it was verified.

Note that the current commit is a mostly AI authored draft intended to iterate
over some design choices.

## Status

| Part | State |
|---|---|
| Specification (`docs/spec.md`) | v0.5; all three parts implemented |
| Assembler (`tools/pasm.py`) | Working |
| Engine (`src/pe_engine.sv`) | Passes 19 simulation tests |
| Host interface and four-engine top level (`src/project.sv`, `pe_spi.sv`, `pe_regs.sv`, `pe_pins.sv`) | Passes 20 whole-chip simulation tests, at RTL and on the gate-level netlist of the layout |
| Example programs (`programs/`) | UART, SPI, I2C, low-speed USB device and 10BASE-T transmit, each run in simulation against a model of the other end; four protocols at once |
| Layout | Passes routing, antenna, DRC and LVS; timing met at 60 MHz at the typical and fast corners, about 47.5 MHz at the slow corner (`docs/writeup.md`, section 6). Hardened locally; the GDS is in `local_build/` |
| Host software (`firmware/`) | MicroPython driver, tested against the RTL; not yet run on a board |
| FPGA build for the PYNQ-Z2 (`fpga/`) | Sources pass the whole-chip tests in simulation; not yet built in Vivado |

## Layout of the repository

| Path | Contents |
|---|---|
| `docs/writeup.md` | Design and verification write-up for the competition |
| `docs/spec.md` | Instruction set, host interface, pins |
| `docs/decisions.md` | What was decided, what is deferred, what is still open |
| `docs/ai_usage.md` | Which files an AI tool wrote and how they were checked |
| `docs/info.md` | Tiny Tapeout datasheet page |
| `programs/` | Example protocol programs |
| `firmware/` | Host software: MicroPython driver for the demo board's RP2350 or another board |
| `fpga/` | Build of the design for the PYNQ-Z2 FPGA board |
| `tools/pasm.py` | Assembler |
| `src/` | Hardware source and the layout configuration |
| `test/` | Simulation tests (cocotb, Icarus Verilog). `test/test.py` tests the whole chip through its pins, with the SPI host model in `test/host.py`; `test/engine/` tests one engine on its own |
| `local_build/` | The hardened layout, committed because the flow takes longer than a GitHub job may run |
| `odb_stripes.py`, `librelane_plugin_jsasic_pdn.py` | Layout-flow step that powers the memory blocks |

## Running the tests

```
pip install -r test/requirements.txt
python test/engine/run.py      # one engine: instruction and protocol tests
cd test && make                # the whole chip, through its pins
```

Both need Icarus Verilog. The memory block's simulation model is in
`test/ihp_sram/`, so no PDK is needed.

To assemble a program and see its words and label addresses:

```
python tools/pasm.py programs/uart_tx.s
```

## Running the layout flow

The layout takes longer than a GitHub job may run, so it is hardened locally,
following https://www.tinytapeout.com/guides/local-hardening/ with the PDK set
to `ihp-sg13cmos5l`, and the result is committed in `local_build/`. The `gds`
workflow publishes that result and runs the Tiny Tapeout precheck and the
gate-level tests on it. Any change to `src/` needs a new local harden.

Host software and the FPGA build: see `firmware/README.md` and
`fpga/README.md`.

## Licence

Apache License 2.0 (`LICENSE`). Files taken from other projects are under the
same licence and keep their own copyright notices; `NOTICE.md` lists them.
