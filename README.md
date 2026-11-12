![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# JaneStreetASIC

A programmable protocol emulator for the Jane Street protocol emulator ASIC
competition, targeting an 8x4 Tiny Tapeout tile on IHP CMOS5L.

The chip holds four small processors ("engines"). Each runs a short program
that reads pins, writes pins and counts time precisely enough to speak a serial
protocol. UART, SPI, I2C and low-speed USB are written as programs; none of
them is built into the hardware.

## Status

| Part | State |
|---|---|
| Specification (`docs/spec.md`) | v0.1 draft |
| Example programs (`programs/`) | Paper drafts, not yet assembled |
| Probe build (`src/project.sv`) | Passes simulation; layout run not done yet |
| Engine, host interface, assembler | Not started |

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
| `src/` | Hardware source and the layout configuration |
| `test/` | Simulation tests (cocotb, Icarus Verilog) |
| `odb_stripes.py`, `librelane_plugin_jsasic_pdn.py` | Layout-flow step that powers the memory blocks |

## Running the tests

```
cd test
pip install -r requirements.txt
make
```

This needs Icarus Verilog. The memory block's simulation model is in
`test/ihp_sram/`, so no PDK is needed.

## Running the layout flow

Push to GitHub: the `gds` workflow builds the layout and runs the Tiny Tapeout
checks. To run it locally, follow
https://www.tinytapeout.com/guides/local-hardening/ with the PDK set to
`ihp-sg13cmos5l`.

## Licence

MIT for original work. Files taken from other projects keep the Apache License
2.0; `NOTICE.md` lists them.
