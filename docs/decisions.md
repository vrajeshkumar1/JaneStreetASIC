# Decisions

Last updated 12 November 2026. Each entry says what was decided and why, so the
reasoning does not have to be reconstructed later.

## Settled

| Topic | Decision | Reason |
|---|---|---|
| Tile and process | 8x4 tiles, IHP CMOS5L, Tiny Tapeout flow | Competition rules; 8x4 confirmed on 9 November 2026 |
| Clock | One 60 MHz clock | The demo board can supply it. It is 40 clocks per low-speed USB bit, which leaves room to do line coding in instructions |
| Reset | Asynchronous assert, synchronized release | Every flip-flop in the cell library has an asynchronous reset pin and none comes without one |
| Engines | Four, as a build parameter | UART in both directions needs two engines; four lets UART, SPI and I2C run together. One engine synthesizes to 0.094 mm2 of cells (682 flip-flops) plus a 0.050 mm2 memory block. Four use about 40% of the area outside the memory blocks; five would use about 52% and six about 65%, above the flow's 60% target |
| Program memory | One 256 x 32 memory block per engine | A sketch of a low-speed USB device came to 120 to 150 instructions. Jump targets are 9 bits so 512 stays possible |
| Instruction word | 32 bits | The memory blocks are 32 bits wide, so the bits are free |
| Registers | Eight 16-bit registers, 8-bit shift registers | The largest value any listed protocol counts is an 11-bit frame length; the I2C target uses 5 registers and the USB sketch about 6 |
| Tick | Whole-number divider, 16 bits | A fractional divider makes tick length vary, which breaks cycle-exact timing. At 60 MHz, 115200 baud is 0.16% off with a whole number |
| Taken jumps | No extra tick | Confirmed by the probe layout run: in the slow corner the memory output arrives 5.34 ns after the clock edge and the loop back to the memory address had 9.0 ns of slack at 60 MHz. The real engine's decode is deeper than the probe's, so this is to be re-checked on the first engine layout |
| Program wrap | Not included | Without it the shortest loop is 2 ticks, a 30 Mbit/s ceiling. Nothing on the protocol list needs more |
| Conditional execution | Every instruction can run only if T is set, or only if T is clear | Both outcomes take the same time, which keeps line-coding loops at a constant length |
| FIFOs | 16 bytes each way, flip-flops | A low-speed USB packet (up to 9 bytes) cannot pause mid-way, so it must fit whole |
| Data memory | 16 bytes per engine, flip-flops | A shared memory block allows one access per clock across all engines |
| Host link | SPI gated by one host-select pin; three pins borrowed during a transfer; a lock bit | The demo board's microcontroller has no private connection to the chip, so every host pin comes out of the 24 |
| Line coding | In instructions, not hardware | Reprogrammability is the main judging criterion |
| General-purpose hardware | Checksum unit, wait time readable, parity and bit reversal | Each has uses in several protocols |
| Ethernet | No Ethernet-specific hardware | It is the only listed protocol that instructions cannot handle at 60 MHz |
| Host for the demo board | RP2350 running Tiny Tapeout's MicroPython firmware | It is what the board ships with. Custom firmware only if a specific need appears |
| Host for the FPGA prototype | Raspberry Pi Pico (RP2040) running MicroPython | The board is marked 2020; the Pico 2 came out in August 2024. The same host script should carry over to the RP2350 |
| Licence | MIT for original work | Owner's choice. Template and third-party files stay Apache-2.0 (`NOTICE.md`) |
| Work split | Owner: board bring-up, design choices, UVM testbench, small edits. AI tool: RTL, assembler, example programs, the template's minimal tests | Recorded for the write-up |

## Chosen while writing the specification

These were not discussed first. Each is small and can be changed before the RTL
depends on it.

| Choice | Alternative |
|---|---|
| `Z` and `C` are set only by `cmp`; `T` is a separate flag written by `tst`, `tbit`, `out` to `T`, parity and wait timeouts | One flag set shared by everything |
| `halt` exists as an instruction, and an illegal word acts as `halt` | Illegal words as no-operations |
| `call` and `ret` share one opcode; `ret` is still written `ret` | Separate opcodes (none are spare) |
| Pin writes (`set pin`, `toggle pin`, `set dir`) have their own opcode | Folding them into `mov` |
| Pin numbers 0 to 7 mean input pins when read and output pins when written | A 5-bit pin number |
| `wait change` watches two pins named in the instruction | A 16-bit pin mask held in a register |
| Host reads have one dummy byte after the address | No dummy byte, with a slower SPI clock |
| Shift direction is a per-engine setting | A bit in each `in` and `out` |
| Open-drain is a per-pin setting on the bidirectional pins | Programs writing the direction themselves |

## Deferred, to revisit

| Item | What it is | When to revisit |
|---|---|---|
| Divider restart on a pin edge | An option that restarts an engine's tick divider when a chosen pin changes, so ticks line up with an incoming signal. Uses: CAN resynchronisation, Manchester-coded links, Ethernet receive | After the four-engine design passes layout |
| One large attachable buffer | A 1,024-byte memory block (49,419 um2, 4% of the die) that the host attaches to one engine's FIFO. Uses: SD card blocks, long captures, Ethernet frames. Without it Ethernet cannot be demonstrated | After the first full layout shows the spare area |
| Input glitch filter | Per pin, accept a change only after 3 identical samples | Only if I2C or PS/2 testing on hardware shows a need |
| Engine count above four | Five engines (six does not fit, see Engines above) | After the four-engine layout shows how routing copes |
| Shared memory block for FIFOs and data memory | Rejected for now: one access per clock across engines | Only if six engines do not fit otherwise |
| USB example role | Device or host | When the USB program is written |
| Custom host firmware | Replacing MicroPython on the RP2350 | If measured host latency makes 16-byte FIFOs too small |

## Found while testing the first engine

| Finding | Consequence |
|---|---|
| Pins are inputs at level 0 after reset, so an open-drain line is pulled low until the program releases it | Every program starts by setting its pin directions and idle levels |
| A `wait` on a line the engine has just released takes two ticks: the engine cannot see its own pin change within the same tick | The I2C controller's delays were reduced by one tick each to keep 6 ticks per bit |
| The checksum unit advances one step per instruction | `feed` is only allowed on one-bit `in` and `out` |
| The cell area outside flip-flops (0.060 mm2) is larger than estimated (0.02 to 0.03 mm2) | Mostly read multiplexers for the flip-flop FIFOs, data memory and registers, and the variable shifters. A candidate for trimming if area gets tight |

## Open questions the probe build answered

All four were answered by the layout run of 12 November 2026: the flow accepts
the tile and the memory block, the SystemVerilog subset passes, the stripes
land on the block (worst voltage drop 0.14 mV), and the loop has 9.0 ns of
slack. The questions were:

1. Does the flow accept an 8x4 tile with a memory block?
2. Which SystemVerilog constructs pass both the synthesis parser and the
   simulator in the flow's tool versions?
3. Do the power stripes land on the memory block's supply columns?
4. How much slack is there in the memory-output-to-memory-address loop at
   60 MHz?
