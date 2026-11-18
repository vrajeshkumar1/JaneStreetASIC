# Programmable Protocol Emulator for IHP CMOS5L: Design and Verification

Vrajesh Kumar. Entry to the Jane Street protocol emulator ASIC competition
[1], [2]. Written 18 November 2026.

This document is the write-up the competition asks for: the architecture and
instruction set in outline, the toolchain and example programs, the
verification approach, the physical design, and the use of AI tools. The full
instruction set and register map are in `docs/spec.md`; the reasoning behind
individual choices, with measurements, is in `docs/decisions.md`; the record
of AI use is in `docs/ai_usage.md`.

## 1. Summary

The chip contains four small processors, called engines, that run protocol
programs from their own memory blocks. Every instruction takes a fixed number
of clock ticks, so a program is also a timing diagram, and the line coding of
a protocol (bit timing, start and stop conditions, bit stuffing, Manchester
or NRZI coding) is done in instructions rather than in protocol-specific
hardware. A host loads programs and exchanges data with the engines over SPI,
using one dedicated pin and three pins it borrows only while it is talking to
the chip; the engines have the other 23 pins, including those three outside
host transfers.

Programs written and simulated so far: UART transmit and receive, SPI
controller, I2C controller and target, a low-speed USB device, and a 10BASE-T
Ethernet transmitter. All four engines can run different protocols at once.

The layout, made with the Tiny Tapeout flow on an 8x4 tile, passes routing,
antenna, DRC and LVS checks and meets timing at 60 MHz at the typical and
fast corners. The slow corner (1.08 V, 125 C) does not meet 60 MHz; there
the limit is about 47.5 MHz (section 6.3).

## 2. Architecture

### 2.1 Overview

| Block | Contents |
|---|---|
| Engines 0 to 3 | Each: eight 16-bit registers, 8-bit input and output shift registers, a TX FIFO and an RX FIFO, a small data memory, test flags, and a program memory of its own (one IHP memory block) |
| Shared flags | Eight one-bit flags that engines and the host set, clear and wait on |
| Host interface | SPI target on `ui_in[0..2]` and `uo_out[0]`, a register file, and access to every engine's program memory and FIFOs |
| Pin block | Per-pin owner selection, open-drain option, output flip-flops and two-stage input synchronisers |

Engines differ in size, because four full-size engines could not be routed
on the tile (section 6.2):

| Engine | Program memory | FIFOs, each way | Data memory | Checksum unit | Shifts |
|---|---|---|---|---|---|
| 0, 1 | 256 words | 8 bytes | 4 bytes | no | one place |
| 2 | 512 words | 8 bytes | 4 bytes | yes | 0 to 15 places |
| 3 | 256 words | 16 bytes | 16 bytes | yes | 0 to 15 places |

The instruction set is the same on all four. A program that fits an engine's
sizes and units runs on any of them, and the host can read each engine's
sizes and units from its `SIZES`, `DM_SIZE` and `FEATURES` registers.

### 2.2 Instruction set

Instructions are 32 bits, one word of the memory block. Each has a 4-bit
opcode, a condition (always, only if the test flag `T` is set, or only if it
is clear), a delay of 0 to 15 extra ticks, and a side-set field that changes
up to two pins on the instruction's first tick. Several ideas come from the
programmable I/O block of the RP2040 [3]: side-set, input and output shift
registers with automatic push and pull at a threshold, and a shift direction
setting. The rest follows from the protocols on the competition's list:

- **Timing rules.** Every instruction that does not stall takes one tick plus
  its delay, taken or not, skipped or not; `ldm` and `stm` take two. A stall
  repeats on the next tick. These rules, with the fixed pin latencies of
  section 2.4, are what make tick-exact protocol code possible.
- **General registers and an ALU.** Eight 16-bit registers with add,
  subtract, logic, shifts and compare, so that a program can count frame
  lengths, hold a device address or compute a pointer.
- **Waits with timeouts.** `wait` stalls on a pin level, on a change of
  either of two pins, or on a shared flag, and can end after a number of
  ticks held in a register, setting `T` to say which happened. Clock
  recovery in the USB program is built from these.
- **Checksum unit** (engines 2 and 3). A 32-bit shift register with a
  host-set polynomial, width and direction, advanced by any one-bit `in` or
  `out` that has its `feed` bit set. It covers the CRCs of USB, Ethernet,
  SD cards, CAN, Modbus and 1-Wire.
- **Byte access to the memory block.** `ldm` and `stm` read and write single
  bytes of the engine's own memory block. Most programs use a small part of
  the block, so the rest of it (1 KB, or 2 KB on engine 2, less the program)
  serves as a data buffer with no extra storage: the I2C target keeps its
  register map there and the Ethernet transmitter its frame.
- **Data movement.** `mov` copies between registers, shift registers, all
  eight pins of a group at once, the checksum, the wait-time counter, the
  program counter (computed jumps) and the shared flags, optionally
  inverting, bit-reversing or computing parity.

Every jump test reads stored bits only, so the jump decision never waits for
the adder; this was chosen for timing (section 6.3).

### 2.3 Host interface

The host is the RP2350 on the Tiny Tapeout demo board, running MicroPython.
The demo board's microcontroller has no private connection to the chip, so
the host link has to come out of the 24 pins. Host select (`ui_in[0]`) is
reserved; while it is high the SPI clock, data-in and data-out pins are
ordinary protocol pins. While it is low, the engines keep running and see
`in1` and `in2` frozen at their levels from before the transfer. A lock bit
gives all 24 pins to the engines once setup is finished.

The SPI clock is sampled with the chip clock, not used as a clock, so the
whole design has one clock domain. The SPI clock may be up to 1/8 of the
chip clock (7.5 MHz). Writes and reads carry a 15-bit address; FIFO
addresses do not advance, so a burst moves several FIFO bytes. A byte leaves
an RX FIFO only after all eight bits have been clocked out, so a transfer
that is cut short loses nothing.

The host can write an engine's registers, data memory and program memory
while the engine is stopped. It cannot read the registers or data memory
back (that read path was removed to save cells, section 6.2); a program
reports values through its RX FIFO instead.

### 2.4 Pins

Each output and bidirectional pin has a two-bit owner field: only its owner
engine can drive it, and an engine can read every pin. Every output passes
through a flip-flop after the owner selection, so all pins change at the
same delay after the clock edge whichever engine drives them, and every
input passes through two flip-flops. An engine therefore writes a pin with
one clock of latency and reads one with two, and these figures are part of
the timing rules programs are written against. Bidirectional pins can be
marked open-drain for I2C and similar buses. Pin drivers are switched on by
the host only after the programs have set their idle levels, so an
open-drain line is never pulled low at start-up.

## 3. Toolchain

| Tool | Purpose |
|---|---|
| `tools/pasm.py` | Assembler: labels, `.define`, `.org`, every operand form of the instruction set; prints words and label addresses |
| `firmware/make_programs.py` | Assembles all of `programs/` into `firmware/programs.py`, a module of word lists and label tables that MicroPython can import |
| `firmware/pe_host.py` | Host driver for MicroPython (and CPython): links for the demo board, for bit-banged pins and for a hardware SPI peripheral; register access; program loading; host-side helpers for the USB and Ethernet programs |
| `firmware/demo.py` | First check on hardware: ID, size registers, a program on each engine, shared flags |
| `fpga/` | Build of the same RTL for the PYNQ-Z2 (section 7) |

## 4. Example programs

| Program | Words | Role | Timing at 60 MHz |
|---|---|---|---|
| `uart_tx.s` | 5 | UART transmitter | 8 ticks per bit; every edge on the exact tick |
| `uart_rx.s` | 9 | UART receiver | 8 ticks per bit; accepts a sender 2% fast or slow |
| `spi_controller.s` | 5 | SPI controller, mode 0, full duplex | 4 ticks per bit |
| `i2c_controller.s` | 33 | I2C controller, commands from the host | 6 ticks per bit; 100 kHz at `CLKDIV` 99 |
| `i2c_target.s` | 58 | I2C target with a 16-byte register map | One tick per clock; tested at 400 kHz |
| `usb_ls_device.s` | 232 | Low-speed USB device (1.5 Mbit/s) | 40 ticks per bit; transmitted transitions on the exact tick; receives from a host 1.5% fast or slow (tested), 4.5% (measured) |
| `eth_tx.s` | 129 | 10BASE-T transmitter | 6 ticks per bit; every half-bit change on the exact tick |

The USB and Ethernet programs show how much of those protocols the engines
do themselves, which the competition asks about [2].

The USB device recovers the bit clock from the data transitions with three
timed waits, undoes NRZI coding and bit stuffing, checks the CRC16 of data
packets in the checksum unit, finds the end of packet, and answers within the
bus turnaround time without the host: ACK to a good data packet, and to an
IN token either the packet the host has prepared or NAK. When sending, it
adds SYNC, bit stuffing, NRZI coding, the CRC16 and the end of packet [4].
The host handles the protocol above packets (requests, descriptors, data
toggles) through the RX and TX FIFOs and a shared flag. The CRC5 of tokens
is not checked, because the checksum unit holds one polynomial at a time.

The Ethernet transmitter takes a frame that the host has written into the
spare part of engine 2's 512-word block, computes the frame check sequence
with the checksum unit, and sends preamble, delimiter, frame and FCS in
Manchester code, then the end-of-frame idle pulse and, while idle, a link
pulse every 16.4 ms [5], [6]. Its bit loop is unrolled over the eight bit
positions of a byte and both values of each bit, so that every bit is
exactly six ticks; the work of fetching the next byte is spread over the
spare ticks of four of the eight bits. Ethernet receive was not written.
Worked through on paper, a receive loop fits, with about one clock of timing
margin either side of the window in which it must look at the line
(`docs/decisions.md`).

The I2C target shows reuse across engines: it keeps its register map in the
memory block, so it runs on engines with 4 bytes of data memory as well as on
engine 3.

Protocols the chip was not designed around can be written in the same way;
none of the following has been written or simulated yet. The pieces exist in
the instruction set for 1-Wire (open-drain pins, timed waits, CRC8 in the
checksum unit), WS2812-style LED data (side-set with tick-exact delays),
PS/2 (open-drain clock and data, parity by `mov`), and SD cards in SPI mode
(the SPI program with CRC7 and CRC16 in the checksum unit).

## 5. Verification

### 5.1 Approach

Verification is done at four levels, all with cocotb [7] and Icarus Verilog.
Every test that involves a protocol checks it against a model of the device
at the other end of the wire, not against the engine's own expectations.

| Level | What is tested | Tests |
|---|---|---|
| One engine | Each instruction, timing rule, FIFO behaviour, checksum mode and shifter variant, with direct access to the engine in place of the host link; the first five protocol programs against bus models | 19 (`test/engine/`) |
| Whole chip, through its pins | The host link (formats, bursts, the borrowed pins, the lock bit, fast host clocks), registers, program loading, pin ownership and open-drain, flags and the attention line, illegal instructions, the per-engine units, every example program, four protocols at once, and the host driver of section 3 | 20 (`test/test.py`) |
| Gate level | The whole-chip tests on the netlist of the hardened layout, with the IHP cell models | 20, passing |
| FPGA source set | The whole-chip tests on the sources the FPGA build uses (flip-flop storage and block-RAM stand-ins in place of the latches and IHP blocks) | 20, passing |

The whole-chip tests reach the design only through its pins, using a model of
the SPI host whose clock is timed in nanoseconds rather than in chip clocks,
as on the real board. A test that needs an internal value has the program
send it through the RX FIFO, as a program on the chip would; this is what
lets the same tests run on the gate-level netlist, where internal storage
has no names.

Bus models (`test/models.py`): UART transmitter and receiver with adjustable
rate error; SPI target; I2C controller and target, open-drain, with clock
stretching; a low-speed USB host that sends NRZI-coded, bit-stuffed packets
with a chosen rate error and skew between D+ and D-, and checks every
transition of the device's reply against the 40-clock bit grid and the
end-of-packet timing; and a 10BASE-T decoder that checks that the two lines
are complementary, that every change falls on the 3-clock half-bit grid,
and that every bit has its mid-bit transition, then compares the frame and
FCS with Python's `zlib.crc32` and measures the end-of-frame pulse.

Timing is checked as well as data. The UART, USB and Ethernet tests require
every transmitted edge on its exact tick; the UART receiver is run against
senders 2% fast and slow and the USB receiver against hosts 1.5% fast and
slow, the limit the USB specification allows a low-speed signal [4].

The host driver that will run on the board (`firmware/pe_host.py`) is itself
run against the RTL: `test_micropython_driver` executes the driver's
blocking code in a thread through cocotb's bridge, with each SPI byte driven
through the simulated pins, and checks the self-test, a USB control-transfer
exchange and an Ethernet frame sent through the driver's helpers with both
engines running.

The tests were also checked for their ability to find faults: eight faults
were put into the design one at a time (for example, pins not frozen during a
host transfer, the lock bit ignored, program writes allowed while an engine
runs), and each made at least one test fail. The tests also found one real
fault, since fixed: a clock pin rising on the same chip clock as host select
fell was counted as an SPI clock edge.

Static checks: Verilator lint is clean, and Yosys synthesis with the CMOS5L
library is used to count cells and to confirm that the only latches are the
intended storage.

### 5.2 UVM testbench

A UVM testbench is being written separately by the author. This section will
describe it.

### 5.3 What has not been verified

- Nothing has run on hardware yet: neither the FPGA build (section 7) nor
  the host driver on a board.
- The timing of the chip is verified only by the flow's static timing
  analysis at three corners (section 6.3); the I/O pads of CMOS5L have no
  characterised figures yet [2].
- The USB device has been tested against a model of a host, not a real one.
  A host computer's exact behaviour during enumeration (retries, timeouts)
  has not been exercised.

## 6. Physical design

### 6.1 Floorplan

The design uses an 8x4 Tiny Tapeout tile on IHP CMOS5L, 1724.16 x 710.64 um,
built with the Tiny Tapeout flow (LibreLane) [8]. Signals route on Metal2
to Metal4; Metal3 is the only layer that runs left to right, and Metal4 also
carries the power stripes. The four memory blocks sit in the corners, each
next to its engine's logic, at positions on the power-stripe grid, with the
512-word block in the bottom-left corner. The method of adding IHP memory
blocks to a tile follows Ken Pettit's walkthrough [9].

### 6.2 History

The present design is the result of several layout runs, each read for where
it failed and changed accordingly. `docs/decisions.md` has the measurements.

| Design and settings | Result | Change made |
|---|---|---|
| Probe: one memory block and a small loop | Passed all checks | Four engines built |
| Four full engines, default settings | Placement failed: the placer predicted congestion over a third of the tile and inflated the cells to fill it | Area-oriented synthesis; routability-driven placement off |
| The same | Detailed routing stalled at about 43,000 violations; the GitHub run exceeded its 6-hour limit | Engines of different sizes; 512-word block for engine 2; `ldm` / `stm` added |
| Unequal engines | About 9,600 to 11,000 violations after 40 passes | 4,566 fewer cells (18%): latch storage for FIFOs and data memories behind clock gates, no checksum unit or long shifter on engines 0 and 1, no host read-back of registers and data memory |
| Fewer cells | 5,849 violations after six passes, over a third of them on top of the 512-word block | Blocks of engines 0 and 2 swapped; routability-driven placement on |
| Swapped blocks | 208 violations after 25 passes, about 145 of them from wires the global router had put across blocked memory areas | Global-routing capacity reduction 30% to 15% |
| 15% reduction | 402 violations in one dense area: placement had spread the cells less | Reduction 20% |
| 20% reduction | Complete run: 92 violations at one block's pin edge, and one LVS short there | 10 um cell-free band along the blocks' pin edges |
| Band, antenna repair margin 30%, 40 routing passes | Routing, antenna, DRC and LVS clean; setup fails at the slow corner | Setup check limited to the typical and fast corners |

The later runs were too long for GitHub's 6-hour job limit, so they were
made outside GitHub with the same flow [10], and the GDS workflow publishes
the committed result.

### 6.3 Final results

| Check | Result |
|---|---|
| Detailed routing | 0 violations |
| Antenna | 0 violations (83 diodes) |
| KLayout DRC | 0 |
| LVS | 0 differences |
| Hold | Met at all three corners |
| Setup, typical (1.20 V, 25 C) and fast (1.32 V, -40 C) | Met at 60 MHz |
| Setup, slow (1.08 V, 125 C) | Fails by 4.36 ns on 786 paths |
| Standard cells | 27,627, of which 5,443 timing-repair buffers, 2,545 sequential cells and 108 clock gates; cells and memory blocks cover 49% of the core |

The failing paths start at a memory block's data output: at the slow corner
the 512-word block takes 6.8 ns from clock to data, and the instruction
decode after it does not fit in the rest of the 16.67 ns period. At that
corner the chip works up to about 47.5 MHz (1 / (16.67 + 4.36) ns). The
specification is therefore 60 MHz at typical conditions. The slow corner
combines slow transistors from the process spread with a supply 10% low and
a junction temperature of 125 C; the demo board regulates the supply, but
which part of the process spread a given chip falls in, and how warm it runs,
are not known before silicon. Closing the slow corner at 60 MHz would need a register
after the memory read, which adds a tick to every instruction and changes
the timing of every program. The protocol programs assume 60 MHz; at a lower
clock, programs whose timing is fixed by the protocol (USB, Ethernet) would
need different tick counts.

## 7. FPGA prototype and host software

`fpga/` builds the unchanged RTL for the PYNQ-Z2 (Zynq XC7Z020) at 60 MHz,
with the design's pins on the two Pmod headers and the Arduino header [11].
The latch storage and the IHP memory blocks are replaced by flip-flops and
block RAM with the same ports; the whole-chip tests pass on that source set.
A MicroPython board wired to the Pmod header is the host. The Analog
Discovery 3 [12] is the other end of the protocols: its logic analyser
decodes UART, SPI, I2C and Manchester code, and at 125 MS/s it samples a
10 Mbit/s Manchester signal about six times per half bit. The Vivado build
and the board tests had not been run when this was written.

On the demo board, the same driver runs on the RP2350 through the board's
MicroPython SDK [13].

## 8. Use of AI tools

The competition allows AI tools and asks for a description of their use
[2]. Claude (Anthropic) was used throughout, through the Claude app.

| Who | What |
|---|---|
| The author | Design decisions (accepting, changing or rejecting each proposal), the layout runs and their settings, board bring-up, the UVM testbench, review and edits |
| Claude | Research into the process, cell library and flow; proposals for the architecture and instruction set; the specification, the RTL, the assembler, the example programs, the cocotb tests and bus models, the host driver, the FPGA build files; analysis of each layout run's reports; most of the documentation |

`docs/ai_usage.md` lists each piece of AI-written work with how it was
checked and what was left unchecked. Code was checked by simulation and by
the tools it was written for; claims about the layout were checked against
the flow's own reports; where an estimate made in the AI tool's workspace differed from the
real run (the early routing estimates, for example), the run's figures were
used and the difference recorded in `docs/decisions.md`.

## References

[1] Jane Street, "Protocol emulator ASIC competition," Jane Street Tech
Blog. <https://blog.janestreet.com/protocol-emulator-asic-competition/>

[2] Jane Street ASIC competition organisers, "Protocol emulator ASIC
competition: update and FAQ," email to entrants, 9 Oct. 2026.

[3] MicroPython, "rp2 — functionality specific to the RP2040," MicroPython
documentation. <https://docs.micropython.org/en/latest/library/rp2.html>

[4] USB Implementers Forum, *Universal Serial Bus Specification*, rev. 2.0,
Apr. 2000, secs. 7.1.8 (NRZI coding), 7.1.9 (bit stuffing) and 7.1.11 (data
signalling rate).

[5] *IEEE Standard for Ethernet*, IEEE Std 802.3, clause 14, "Twisted-pair
medium attachment unit (MAU) and baseband medium, type 10BASE-T."

[6] University of New Hampshire InterOperability Laboratory, "10BASE-T MAU,"
knowledge base.
<https://www.iol.unh.edu/sites/default/files/knowledgebase/ethernet/10basetmau.pdf>

[7] cocotb contributors, *cocotb* documentation. <https://docs.cocotb.org/>

[8] Tiny Tapeout, "Tiny Tapeout." <https://tinytapeout.com/>

[9] K. Pettit, "Adding an IHP SRAM macro to a CMOS5L tile."
<https://kdp1965.github.io/ihp-um-janestreet-prism/ihp_sram_macro.html>

[10] Tiny Tapeout, "Local hardening."
<https://tinytapeout.com/guides/local-hardening/>

[11] TUL, *PYNQ-Z2 Reference Manual*, v1.0.

[12] Digilent, *Analog Discovery 3 Specifications*.
<https://assets.testequity.com/te1/Documents/pdf/digilent/Digilent_Analog-Discovery-3-Specifications_1123.pdf>

[13] Tiny Tapeout, "tt-micropython-firmware."
<https://gitee.com/mirrors_urish/tt-micropython-firmware>
