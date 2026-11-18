# Tests

Simulation tests with [cocotb](https://docs.cocotb.org/en/stable/) and Icarus
Verilog. Derived from the Tiny Tapeout template's sample testbench.

| File | What it is |
|---|---|
| `tb.v` | The whole chip plus the wires outside it |
| `test.py` | Whole-chip tests (20). They reach the design only through its pins, so they also run on the gate-level netlist. A test that needs a register or data-memory value has the program send it through the RX FIFO (`report()` in `host.py`), as a program on the real chip would. `test_micropython_driver` runs the board's host driver (`../firmware/pe_host.py`) against the design, through cocotb's bridge between blocking code and the simulation |
| `host.py` | Model of the host: an SPI controller that speaks the host link of `docs/spec.md`, part 2, with helpers to load programs and settings |
| `models.py` | Models of the other end of the wire: UART, SPI target, I2C target and controller, a low-speed USB host, and a 10BASE-T receiver that checks the line timing and decodes frames |
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
To run it locally, copy the netlist of the hardened layout to
`gate_level_netlist.v` (`../local_build/nl/tt_um_vrajeshkumar1_janestreetasic.nl.v`,
or `../runs/wokwi/final/nl/` after a layout run) and point `PDK_ROOT` at the
PDK, then

```sh
make -B GATES=yes
```

One test only:

```sh
COCOTB_TEST_FILTER=test_fifos make -B
```

The filter is a regular expression, but it is passed through the shell
unquoted, so it must not contain `|`.

The whole-chip tests on the FPGA build's sources (flip-flop storage and
block-RAM stand-ins): `python ../fpga/sim_fpga_sources.py`.

## Waveforms

```sh
gtkwave tb.fst tb.gtkw
```

or

```sh
surfer tb.fst
```
