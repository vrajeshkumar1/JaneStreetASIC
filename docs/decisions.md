# Decisions

Last updated 12 November 2026. Each entry says what was decided and why, so the
reasoning does not have to be reconstructed later.

## Settled

| Topic | Decision | Reason |
|---|---|---|
| Tile and process | 8x4 tiles, IHP CMOS5L, Tiny Tapeout flow | Competition rules; 8x4 confirmed on 9 November 2026 |
| Clock | One 60 MHz clock | The demo board can supply it. It is 40 clocks per low-speed USB bit, which leaves room to do line coding in instructions |
| Reset | Asynchronous assert, synchronized release | Every flip-flop in the cell library has an asynchronous reset pin and none comes without one |
| Engines | Four, as a build parameter | UART in both directions needs two engines; four lets UART, SPI and I2C run together. One engine synthesizes to 0.091 mm2 of cells plus a 0.050 mm2 memory block; the host registers add 0.040 mm2 and the pin and SPI logic 0.009 mm2. The whole four-engine design is 0.414 mm2 of cells (3,259 flip-flops), about 41% of the area outside the memory blocks. A fifth engine would bring that to about 54% and a sixth to about 68%, above the flow's 60% target |
| Program memory | One 256 x 32 memory block per engine | A sketch of a low-speed USB device came to 120 to 150 instructions. Jump targets are 9 bits so 512 stays possible |
| Instruction word | 32 bits | The memory blocks are 32 bits wide, so the bits are free |
| Registers | Eight 16-bit registers, 8-bit shift registers | The largest value any listed protocol counts is an 11-bit frame length; the I2C target uses 5 registers and the USB sketch about 6 |
| Tick | Whole-number divider, 16 bits | A fractional divider makes tick length vary, which breaks cycle-exact timing. At 60 MHz, 115200 baud is 0.16% off with a whole number |
| Taken jumps | No extra tick | The probe layout run showed the memory output arriving 5.34 ns after the clock edge in the slow corner. A trial placement and global route of the four-engine design (see "Found while building the four-engine design") puts the whole loop, memory output through decode to memory address and to the registers, at about the full 16.66 ns in the slow corner and at about 10.4 ns in the typical corner. To be confirmed by the real layout run |
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

## Chosen while writing the host interface and the top level

These were not discussed first either.

| Choice | Reason | Alternative |
|---|---|---|
| Register numbers and pin numbers sit in the same bits of every instruction (register read A in 12:10, register read B in 9:7, pin in 16:13) | The engine can start the register read as soon as the word leaves the memory, without decoding the opcode first. Measured on a trial placement in the slow corner: the longest path went from 16.3 ns to 15.3 ns, and the area fell by 1%. Only the encoding changed; the assembler notation is the same | The v0.2 layout, where each instruction put its register wherever was convenient |
| Every output pin has a flip-flop after the owner selection | All pins change at the same delay after the clock edge, whichever engine drives them and wherever it sits on the die. Costs one clock of latency (timing rule 6) | Driving the pins from the engines' own flip-flops through the selection logic |
| SPI data to the host changes after the rising edge, not the falling edge | The clock is sampled, so the chip reacts 2 to 5 clocks after an edge. Changing after the rising edge leaves a whole SPI clock period for the bit to reach the host instead of half | Changing after the falling edge, which halves the fastest usable SPI clock |
| A FIFO byte is removed only when the host has clocked out all 8 bits | A transfer cut short, or the extra clock edge when the host puts the borrowed clock pin back to a high level, cannot lose a byte | Removing the byte when it is loaded into the SPI shift register |
| The host reaches a program memory, the registers and the program counter only while that engine's `ENABLE` bit is 0 | The memory block has one port; the engine needs it on every tick while running | A halted engine also giving way to the host |
| `DRIVE_OUT` and `DRIVE_IO` are written after `ENABLE` | Pin levels are 0 after reset. Starting the program first lets it set its idle levels before the drivers are connected | A host-writable starting level per pin |
| The lock bit also turns `in0`, `in1`, `in2` and `out0` into ordinary pins | Lets a finished setup use all 24 pins | Keeping host select reserved after the lock |
| Memory blocks in the four corners, the top-left one moved right to x = 273 | The tile's own pins are on the top edge between x = 30 and x = 191. Each engine's logic can sit next to its memory block. Every block is on the same stripe and routing-track position as the block that passed the probe run | All four along the bottom edge (they do not fit on the stripe grid: 4 x 449.6 um is wider than the tile) |

## Deferred, to revisit

| Item | What it is | When to revisit |
|---|---|---|
| Divider restart on a pin edge | An option that restarts an engine's tick divider when a chosen pin changes, so ticks line up with an incoming signal. Uses: CAN resynchronisation, Manchester-coded links, Ethernet receive | After the four-engine design passes layout |
| Fixed-position register write number | The register an instruction writes is still in one of four places (18:16, 15:13, 12:10, 7:5). It is not on the longest path today | If the layout run shows the register write path failing |
| One large attachable buffer | A 1,024-byte memory block (49,419 um2, 4% of the die) that the host attaches to one engine's FIFO. Uses: SD card blocks, long captures, Ethernet frames. Without it Ethernet cannot be demonstrated | After the first full layout shows the spare area |
| Input glitch filter | Per pin, accept a change only after 3 identical samples | Only if I2C or PS/2 testing on hardware shows a need |
| Engine count above four | Five engines (six does not fit, see Engines above). The host address map and the two-bit pin owner fields hold four, so a fifth also needs a wider map | After the four-engine layout shows how routing and timing cope |
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

## Found while building the four-engine design

| Finding | Consequence |
|---|---|
| An engine sees a pin it has written four clocks after the start of the next tick: one clock for the output flip-flop, two for the input synchronizer (`test_pin_round_trip`) | A `wait` on a line the engine has just released takes two ticks only when a tick is at least four clocks (five on the chip, allowing for pad delay). The I2C programs run at 10 clocks per tick or more |
| The host link works in simulation with an SPI clock period down to about 5 chip clocks | The specification asks for 8, leaving 3 clocks (50 ns) for pad and board delays |
| Trial placement and global route with OpenROAD 26Q3 in the AI tool's workspace (Yosys netlist, the PDK's slow and typical timing libraries, memory blocks at their final positions; no power grid, no detailed route, so not the Tiny Tapeout flow): no routing overflow, Metal2 45% and Metal3 51% used; worst setup slack at 60 MHz between -0.2 and +0.8 ns in the slow corner (1.08 V, 125 C) depending on the run, and +6.2 ns in the typical corner (1.20 V, 25 C) | 60 MHz has ample margin at typical conditions and none at the slow corner. The real layout run decides. If the slow corner fails there, the choices are a lower clock for worst-case conditions (48 MHz is still a whole number of clocks per USB bit) or a timing-driven synthesis setting |
| A clock pin that rose on the same chip clock as host select fell was counted as an SPI clock edge, shifting the whole transfer by one bit. Found by the FIFO test once it ran with `in1` idling high | Fixed in `src/pe_spi.sv`: a rising edge counts only after the pin has been seen low while selected |
| The same synthesized netlist passes the whole-chip tests in gate-level simulation | The design does not depend on simulation-only behaviour such as undefined memory contents |
| The memory block's address pins need 0.85 ns of hold time in the slow corner, more than a flip-flop followed by one gate provides | The flow will add delay cells on the address pins, as the trial run did. They sit on the longest path, so this is one place the real run may differ from the trial |

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
