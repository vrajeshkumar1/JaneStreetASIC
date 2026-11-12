# Tests

Simulation tests with [cocotb](https://docs.cocotb.org/en/stable/) and Icarus
Verilog. Derived from the Tiny Tapeout template's sample testbench.

| File | What it is |
|---|---|
| `tb.v` | The whole chip plus the wires outside it |
| `test.py` | Whole-chip tests. They reach the design only through its pins, so they also run on the gate-level netlist |
| `host.py` | Model of the host: an SPI controller that speaks the host link of `docs/spec.md`, part 2, with helpers to load programs and settings |
| `models.py` | Models of the other end of the wire: UART, SPI target, I2C target and controller |
| `engine/` | Tests of one engine on its own, with direct access in place of the host link (`python test/engine/run.py`) |
| `ihp_sram/` | The PDK's simulation model of the memory block |

## How to run

RTL simulation:

```sh
make -B
```

`PROJECT_SOURCES` in `Makefile` must list the same files as `source_files` in
`../info.yaml`.

Gate-level simulation: the GitHub `gds` workflow runs it as its `gl_test` job.
To run it locally, copy the gate-level netlist that the layout run produced to
`gate_level_netlist.v` (the template's instructions give its place as
`../runs/wokwi/results/final/verilog/gl/<top module>.v`), then

```sh
make -B GATES=yes
```

One test only:

```sh
COCOTB_TEST_FILTER=test_fifos make -B
```

## Waveforms

```sh
gtkwave tb.fst tb.gtkw
```

or

```sh
surfer tb.fst
```
