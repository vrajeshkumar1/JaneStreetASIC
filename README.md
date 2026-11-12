![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# JaneStreetASIC

A programmable protocol emulator for the Jane Street protocol emulator ASIC
competition, targeting an 8x4 Tiny Tapeout tile on IHP CMOS5L.

The chip holds four small processors ("engines"). Each runs a short program
that reads pins, writes pins and counts time precisely enough to speak a serial
protocol. UART, SPI, I2C and low-speed USB are written as programs; none of
them is built into the hardware.

Note that the current commit is a mostly AI authored draft intended to iterate
over some design choices.

## Status

| Part | State |
|---|---|
| Specification (`docs/spec.md`) | v0.2; part 1 implemented |
| Assembler (`tools/pasm.py`) | Working |
| One engine (`src/pe_engine.sv`) | Passes 18 simulation tests; not yet in the layout |
| Example programs (`programs/`) | UART, SPI and I2C run in simulation against bus models |
| Host interface, four-engine top level | Not started |
| Probe build (`src/project.sv`) | Passed the layout flow; still the design the layout builds |

`src/project.sv` is currently a probe, not the emulator. It places one memory
block in the tile and exercises it, to check the layout flow before the real
design is written. The comment at the top of that file lists what it checks.

## Layout of the repository

| Path | Contents |
|---|---|
| `docs/spec.md` | Instruction set, host interface, pins |
| `docs/decisions.md` | What was decided, what is deferred, what is still open |
| `docs/ai_usage.md` | Which files an AI tool wrote and how they were checked |
| `docs/info.md` | Tiny Tapeout datasheet page |
| `programs/` | Example protocol programs |
| `tools/pasm.py` | Assembler |
| `src/` | Hardware source and the layout configuration |
| `test/` | Simulation tests (cocotb, Icarus Verilog); `test/engine/` holds the engine's |
| `odb_stripes.py`, `librelane_plugin_jsasic_pdn.py` | Layout-flow step that powers the memory blocks |

## Running the tests

```
pip install -r test/requirements.txt
python test/engine/run.py      # the engine: instruction and protocol tests
cd test && make                # the probe build
```

Both need Icarus Verilog. The memory block's simulation model is in
`test/ihp_sram/`, so no PDK is needed.

To assemble a program and see its words and label addresses:

```
python tools/pasm.py programs/uart_tx.s
```

## Running the layout flow

Push to GitHub: the `gds` workflow builds the layout and runs the Tiny Tapeout
checks. To run it locally, follow
https://www.tinytapeout.com/guides/local-hardening/ with the PDK set to
`ihp-sg13cmos5l`.

## Licence

MIT for original work. Files taken from other projects keep the Apache License
2.0; `NOTICE.md` lists them.
