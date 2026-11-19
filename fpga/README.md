# FPGA build for the PYNQ-Z2

The design from `src/` on the PYNQ-Z2's FPGA fabric (Zynq XC7Z020) at the
chip's clock of 60 MHz, with its 24 pins on the board's headers, so that the
programs and the host software can be tried on real wires before the chip
exists.

| File | Contents |
|---|---|
| `pynq_z2_top.v` | Top level: clock (125 MHz board clock to 60 MHz in an MMCM), reset, pins, LEDs |
| `pynq_z2.xdc` | Pin and clock constraints |
| `fpga_ram.v` | Block-RAM stand-ins for the two IHP memory blocks, with the same ports and byte masks |
| `pe_lmem_ff.sv` | Flip-flop version of the latch storage used for the FIFOs and data memories |
| `build.tcl` | Vivado batch build |
| `sim_fpga_sources.py` | Runs the whole-chip tests on the FPGA source set |

The chip's FIFOs and data memories are latches behind clock gates
(`pe_lmem` and `pe_clkgate` in `src/pe_fifo.sv`). Neither suits an FPGA, so the
build reads a copy of `pe_fifo.sv` with those two modules removed and uses
`pe_lmem_ff.sv` in their place. Every other source file is read unchanged.

## Building and loading

From the top of the repository:

```sh
vivado -mode batch -source fpga/build.tcl
```

The bitstream is written to `fpga/build/pynq_z2_top.bit`, with timing and
utilisation reports beside it. Set the boot jumper JP1 to JTAG [1, section
4], connect the micro-USB port J8 (PROG UART) [1, section 12], and load the
bitstream with the Vivado hardware manager.

| LED | Meaning |
|---|---|
| LED 0 | Clock generator locked |
| LED 1 | Design held in reset (BTN0 pressed, or clock not locked) |
| LED 2 | Host select low (a host transfer in progress) |
| LED 3 | `uo_out[0]` |

BTN0 resets the design.

## Pins

Pin numbers from the PYNQ-Z2 user manual [1]. On each Pmod header, pins 1 to
4 carry bits 0 to 3 and pins 7 to 10 carry bits 4 to 7; pins 5 and 11 are
ground and 6 and 12 are 3.3 V.

| Design pins | Board | FPGA pins |
|---|---|---|
| `ui_in[0..3]` | Pmod JA, pins 1 to 4 | Y18, Y19, Y16, Y17 |
| `ui_in[4..7]` | Pmod JA, pins 7 to 10 | U18, U19, W18, W19 |
| `uo_out[0..3]` | Pmod JB, pins 1 to 4 | W14, Y14, T11, T10 |
| `uo_out[4..7]` | Pmod JB, pins 7 to 10 | V16, W16, V12, W13 |
| `uio[0..7]` | Arduino header AR0 to AR7 | T14, U12, U13, V13, V15, T15, R16, U17 |

The Arduino pins pass through 200 ohm series resistors on the board [1]. Host
select (`ui_in[0]`, JA1) has the FPGA's pull-up, so the design sees no host
while nothing is connected.

## Host

The host is any MicroPython board with `firmware/pe_host.py` (see
`firmware/README.md`), wired to:

| Signal | Board pin |
|---|---|
| Host select (active low) | JA1 |
| SPI clock | JA2 |
| Data, host to chip | JA3 |
| Data, chip to host | JB1 |
| Ground | JA5 or JB5 |

The host's I/O must be 3.3 V. `demo.run(link)` is the first check.

The Analog Discovery 3 can be the host instead, from a PC, with
`firmware/ad3_host.py`: DIO 0 to JA1, DIO 1 to JA2, DIO 2 to JA3, DIO 3 to JB1,
and ground. `python firmware/ad3_host.py` runs the self-test; `--uart` then
starts `uart_tx` on `out4`. The AD3's SPI function needed two adjustments,
both found on the board: at 1 MHz and below it reads the chip's data a bit
late (the chip changes it shortly after each rising edge, as section 2.1 of
the specification allows), so the link runs at 4 MHz; and it returns the last
few bits of each call as 0, so the link sends one bit per SPI word with seven
padding bits at the end, which the chip discards as an unfinished byte.
`--sweep`, `--mosi` and `--diag` are the checks used to find these.

## Protocol checks with the Analog Discovery 3

The Analog Discovery 3 has 16 digital lines at 3.3 V, a logic analyser at up
to 125 MS/s with a buffer of 32,768 samples per line, and interpreters for
UART, SPI, I2C and Manchester codes, among others [2].

| Program | Pins | Check |
|---|---|---|
| `uart_tx.s`, `uart_rx.s` | `out4` (JB7), `in3` (JA4) | WaveForms protocol tool as the other end of the UART |
| `spi_controller.s` | `io0`..`io3` (AR0 to AR3) | Logic analyser with the SPI interpreter |
| `i2c_controller.s`, `i2c_target.s` | `io6` (SCL, AR6), `io7` (SDA, AR7) | Pull-ups of a few kilohms to 3.3 V on both lines; the protocol tool as the other end, or the logic analyser |
| `eth_tx.s` | `out6` (TD+, JB9), `out7` (TD-, JB10) | Logic analyser at 125 MS/s (about 6 samples per half bit at 10 Mbit/s); a 60-byte frame with preamble and FCS lasts 57.6 us, 7,200 samples. The FCS can be compared with `zlib.crc32` of the frame |
| `usb_ls_device.s` | `io4` (D+, AR4), `io5` (D-, AR5) | Logic analyser on both lines. A USB host computer needs a 1.5 kohm pull-up from D- to 3.3 V and a common ground; the host software answers only at packet level (no enumeration code yet) |

## Status

- `python fpga/sim_fpga_sources.py` runs all 20 whole-chip tests in Icarus
  Verilog on the FPGA source set (the stand-ins for the memory blocks and
  latches, with the rest of `src/`); they pass.
- The Vivado build meets timing at 60 MHz on the XC7Z020 (checked in the
  reports in `fpga/build/`).
- On the board (19 Nov 2026): the bitstream loads and the self-test passes
  with the Analog Discovery 3 as the host. The protocol programs have not
  been tried yet.

## References

[1] TUL, *PYNQ-Z2 Reference Manual*, v1.0.

[2] Digilent, *Analog Discovery 3 Specifications*.
<https://assets.testequity.com/te1/Documents/pdf/digilent/Digilent_Analog-Discovery-3-Specifications_1123.pdf>
