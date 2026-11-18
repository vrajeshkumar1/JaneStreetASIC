# Decisions

Last updated 18 November 2026. Each entry says what was decided and why, so the
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
| Licence | Apache License 2.0 for the whole repository (original work was MIT until 18 Nov 2026) | Owner's choice. Template and third-party files are under the same licence and keep their notices (`NOTICE.md`) |
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
| First trial placement and global route in the AI tool's workspace (OpenROAD 26Q3, a Yosys netlist of 0.41 mm2, no power grid, no capacity reduction) reported no routing overflow and Metal3 51% used | That figure was too optimistic and should not be relied on: the trial left out the flow's 30% reduction of routing capacity, its power stripes and the blockages over the memory blocks, and used a smaller netlist than the flow's default synthesis produces. See the next section. Its timing figures (about 0 ns of setup slack in the slow corner, +6.2 ns in the typical corner) were measured the same way and are estimates only |
| A clock pin that rose on the same chip clock as host select fell was counted as an SPI clock edge, shifting the whole transfer by one bit. Found by the FIFO test once it ran with `in1` idling high | Fixed in `src/pe_spi.sv`: a rising edge counts only after the pin has been seen low while selected |
| The same synthesized netlist passes the whole-chip tests in gate-level simulation | The design does not depend on simulation-only behaviour such as undefined memory contents |
| The memory block's address pins need 0.85 ns of hold time in the slow corner, more than a flip-flop followed by one gate provides | The flow will add delay cells on the address pins, as the trial run did. They sit on the longest path, so this is one place the real run may differ from the trial |

## The first four-engine layout run (13 Nov 2026)

The run on GitHub stopped at step 33 of the flow with "Detailed placement
failed" for one cell. The cause was upstream of that step.

| Finding | Source | Consequence |
|---|---|---|
| The flow synthesized with its `DELAY 4` recipe: 0.497 mm2 of cells, of which 9,559 were buffers | Run log, step 6 | 20% more cells than the area-oriented recipe gives |
| Global placement runs in "routability-driven" mode: where it predicts routing congestion it inflates the cells to push them apart. It predicted congestion in a third of the tile, inflated the cells by 76% and filled the whole core, including the 85 um strips beside the right-hand memory blocks. A cell in the top-right strip then had no legal position within the allowed displacement | Run log, step 29: "Number of overflowed tiles: 8117 (34.66%)", "Final placement area: 955325 (+76.21%)" | The placement failure is a symptom of predicted routing congestion |
| The tile routes signals on three layers only (Metal2 to Metal4). Metal2 and Metal4 run top to bottom; Metal3 is the only layer that runs left to right. Metal4 also carries the power stripes (19% of it in this floorplan). The flow reduces every layer's capacity by a further 30% as a safety margin | Run configuration (`RT_MAX_LAYER`, `GRT_ADJUSTMENT`), stripe geometry in the placed design | Left-to-right wiring is the scarce resource. Global routing of the run's own placement wants 103% of the reduced Metal3 capacity (72% of the unreduced capacity) |
| With the area-oriented recipe (`AREA 0`) the same design is 0.41 mm2 with one buffer. With that and routability-driven placement off, the real flow run locally places the design, builds the clock tree and finishes global routing: Metal3 at 78% of the reduced capacity, some congestion left, setup slack +6.2 ns in the typical corner | Local run of LibreLane 3.1.0.dev4, the version the GitHub run used, with the same PDK version, OpenROAD 26Q3 | These two settings are now in `src/config.json` |
| One engine on its own, placed and routed locally with those settings: detailed-routing violations 8192, 5140, 4850, 315, 69, 36, 36, 2 over eight passes. The probe design shows the same shape in the real flow (216, 59, 63, 1, 1, 0) and locally (359, 105, 102, 5, 1, 1, 0) | Local runs; probe run log | An engine's logic is routable at the flow's 60% placement density. The large counts in the first three passes are normal for this cell library (they are pin-access conflicts on Metal2 and clear on the fourth pass) |
| Four engines: detailed routing was run locally for two passes only (66,881 then 45,607 violations; a pass takes 40 to 50 minutes on two processor cores). That is the same ratio as the one-engine run at that point, but one in four of the violations is on Metal3 or Metal4, where the one-engine run had almost none | Local run | Not known yet whether four full engines finish detailed routing. The GitHub run decides |
| Smaller variants, global routing only (share of reduced Metal3 capacity; remaining congestion): three engines 56%, low; four engines with 8-byte FIFOs 73%; four engines with 8-byte FIFOs and 8-byte data memory 63%, low | Local runs | The fallback if four full engines do not route. FIFO depth and data memory size are now parameters of `pe_engine` (`FIFO_AW`, `DM_AW`), set in `src/project.sv` |
| Halving the power stripes over the memory blocks (`EXTEND_STRIPES_SRAM_ARRAY_EVERY_OTHER` off) takes the stripes from 19.4% to 12.5% of Metal4 | Local run of the power-grid steps | Not applied: Metal4 is not the scarce layer, and the present setting is the one that passed the probe run's checks. Available if top-to-bottom routing becomes the limit |

## Unequal engines (13 Nov 2026)

The four-engine design with the changed flow settings was hardened locally by
the author: detailed routing stalled at about 43,000 violations by its 11th
pass, and the GitHub run of the same design exceeded the 6-hour job limit.
Four full-size engines do not fit the tile's routing. The author chose to keep
four engines and make them different sizes.

| Decision | Reason | Alternative |
|---|---|---|
| Engines 0 and 1: 8-byte FIFOs, 4-byte data memory | UART, SPI and I2C do not need more; two 16-byte FIFOs alone are a quarter of a full engine's cells | Three full engines, which loses the four-protocols-at-once demonstration |
| Engine 3 keeps 16-byte FIFOs and 16 bytes of data memory | A low-speed USB data packet is up to 9 bytes after the checksum unit supplies the last two, which does not fit an 8-byte FIFO | The same size as engines 0 and 1, to be tried only if this design routes and an application needs it |
| Engine 2 has a 512-word memory block (IHP 512 x 32, 416.64 x 191.34 um) | 2,048 bytes hold a program and a full 1,526-byte Ethernet frame. The host link is slower than 10 Mbit/s, so a frame has to be in the chip before it is sent. The block has the same width and power columns as the 256-word one | A separate 1,024-byte buffer block shared between engines |
| `ldm` / `stm`: one byte of the engine's own memory block, two ticks | Gives every engine a large byte memory with no new storage: the largest example program uses 55 of 256 words. The block has one port, so the access takes the tick in which the next instruction would have been fetched, and the fetch follows on the second tick | Replacing the flip-flop data memory altogether (the author wants one-tick `ld` / `st` kept) |
| `ldm` / `stm` are a mode bit of `ld` / `st` | All 16 opcodes are in use; bit 18 of both was free | |
| Program memory at 0x4000 + 0x800 x e in the host map; `SIZES` and `DM_SIZE` registers | Room for 512 words per engine; the host can read what each engine has instead of assuming | |

Measured for this design with the real flow run locally up to the clock tree
stage: 0.344 mm2 of cells after synthesis (four full engines: 0.409), Metal3
at 68% of the flow's reduced capacity in a quick global route (four full
engines: 78%), setup slack +6.4 ns in the typical corner. Detailed routing was
left to the author's machine.

Chosen by the AI tool without asking: the two-tick timing (the author had
allowed three), the register-only address of `ldm` / `stm` (an offset would
put an adder in front of the memory address, the slowest path in the design),
the `SIZES` / `DM_SIZE` registers, the `.org` directive, and the block's
position (same corner as before, y = 514.08).

## Fewer cells (14 Nov 2026)

The unequal-engine design was hardened by the author on an 88-vCPU machine:
detailed routing stayed at about 9,600 to 11,000 violations after more than 40
passes. The tile has three routing layers and only Metal3 runs left to right;
the competition page suggests about 1,000 logic cells per tile (32,000 for
this project) and the design had 33,231 after the clock tree stage. Moving the
memory blocks, lowering the placement density and thinning the power stripes
were tried in the flow and did not remove the overflow, so the cell count was
reduced instead. The author chose the list; cell counts are from Yosys with
the flow's area-oriented recipe, before buffering.

| Change | Cells saved | Cost |
|---|---|---|
| FIFO and data-memory bytes kept in latches behind clock gates (`pe_lmem` in `src/pe_fifo.sv`) instead of flip-flops with a write multiplexer | 2,250 | 864 latches and 108 clock-gate cells in the design; timing of these paths relies on the flow's latch analysis (below) |
| No checksum unit on engines 0 and 1 | 1,163 | Those engines cannot compute a CRC in hardware |
| Shifts by one place only on engines 0 and 1 | 546 | A longer shift takes a loop |
| Host cannot read `r0`..`r7` or the data memory | 607 | No register visibility for the host on the chip; a program sends values to the host through its RX FIFO instead (`report()` in `test/host.py`, used by the whole-chip tests since 18 Nov so that they also run on the gate-level netlist) |
| Total: 25,358 to 20,792 | 4,566 | |

Not done: moving engine 1's FIFOs into its memory block. The author had
approved it. A synthesis with engine 1's FIFOs cut from 8 bytes to 2 saved 195
cells, so removing them entirely saves about 260 before the address counters,
the two-clock access sequencing and the buffer registers it would need are
added back, and it would add a rule that engine 1 must leave free clocks for
host FIFO access. Latches had already taken most of what the move would save.

How the latch storage is kept safe: the byte to store is first captured in a
flip-flop; the latch enable comes only from a library clock-gate cell
(`sg13cmos5l_lgcp_1`), whose enable is taken while the clock is low; the
latches follow the flip-flop for the high half of one clock and close half a
clock before it can change. Static timing in the flow run reports the latch
hold check met by 8.4 ns and the clock-gate enable check by 0.5 ns (slow
corner, placement estimate). The latches have a reset, so the data memory is
still zero after reset. In simulation the clock gate is a behavioural
description; `PE_USE_LIB_CELLS` (set in `src/config.json`) selects the cell.

Measured with the real flow run locally up to the clock tree stage, power
stripes over the memory arrays also removed (`EXTEND_STRIPES_SRAM_ARRAY_EVERY_OTHER`
false): 26,724 standard cells (33,231 before), of which 1,983 are hold-time
buffers the earlier run did not insert (it inserted 10; the paths are from
flip-flops to the memory blocks' inputs and exist in both designs). Metal3 at
58% of the flow's reduced capacity in a quick three-iteration global route
(68% before) with an overflow of 4,230 (7,335 before, measured the same way).
The overflow is lower but not zero; detailed routing has not been run.

Known side effect: the flow's timing-repair step counts the 864 latch inputs
as setup violations it cannot repair (they borrow time by design and report a
slack of exactly zero, inside its 0.05 ns margin). It spent about five minutes
on them and changed nothing.

## Where the violations are (16 Nov 2026)

The reduced design was hardened by the author twice. Without routability-driven
placement the result was the same as before the reduction: 9,704 violations at
the best of 32 passes. With it, and with the violation report saved after every
pass, six passes left 5,849 (20,278 at the same pass without it). This was the
first time the positions of the violations were available.

| Where | Violations after six passes |
|---|---|
| On top of the 512-word block (`u_mem2`, then at the top, x = 273 to 690) | 2,215 |
| On top of engine 0's block (`u_mem0`) | 123 |
| Elsewhere, most of it directly under `u_mem2` and to its right (x = 450 to 780) | 3,511 |
| Right of x = 1,050 (engines 1 and 3 and their blocks) | almost none |

On the block the violations are Metal4 shorts between signal wires and the
block, its power stripes and the routing blockage. The global router had put
wires across the block although it is blocked on every layer: with congestion
allowed it prefers a blocked area to a more congested open one, and the block
took 191 um of the 711 um of height in the busiest part of the design, with
`u_mem0` taking another 119 um below it between x = 273 and 420.

Change: the two blocks swap places. The large block is in the bottom-left
corner and engine 0's block, which is 72 um shorter, is at the top. Measured
with the real flow to the clock tree stage and a quick three-iteration global
route, routability-driven placement on in both: Metal3 overflow 3,459 before,
1,867 after; wiring put across the two blocks 581 track segments before, 257
after. Three other arrangements on the power-stripe grid were tried and were
no better than the old one (3,540, 3,748 and 4,801). Detailed routing of the
new arrangement has not been run.

Open fault: in the author's last run the clock tree step left the clock input
of two of the 108 clock-gate cells unconnected (`g_eng[2]...u_rx...g_byte[7]`
and `g_eng[3]...u_tx...g_byte[8]`). The flow reports it at the end as "2
critical disconnected pins". It did not happen in the author's previous run or
in seven local runs, and running the clock tree step locally on the same
placement did not reproduce it, so the cause is not known. A run with this
error must not be used.

## Wires across the memory blocks (17 Nov 2026)

With the blocks of engines 0 and 2 swapped and routability-driven placement,
the author's run reached 208 violations after 25 detailed-routing passes. The
violation reports per pass show where the remainder is:

| Pass | On the 512-word block (`u_mem2`) | On engine 0's block (`u_mem0`) | Open area |
|---|---|---|---|
| 8 | 187 | 247 | 675 |
| 16 | 140 | 68 | 148 |
| 24 | 144 | 26 | 38 |

The open area and `u_mem0` kept falling; `u_mem2` stayed at about 145 for
ten passes. Those violations come from seven nets whose pins are all outside
the block (for example `_06740_`, from x = 290 to x = 535 just above the block)
but whose global-routing guides run through it. The block is blocked on all
three routing layers, so the detailed router cannot make those wires legal
whatever the number of passes.

The global router puts wires there only as overflow: with its default 30%
capacity reduction it saw 1,875 units of Metal3 overflow, while the detailed
router resolved the open-area part of it to about 40 violations, so the
reduction is more pessimistic than the real routing. On the author's placement,
a quick global route with a 15% reduction gave a Metal3 overflow of 37 against
1,781, and no wire across any block against 260 units of usage over
`u_mem0` and `u_mem2`. The same setting also changes routability-driven
placement; a placement made with it (real flow, run locally to the clock tree
stage) gave an overflow of 40 and nothing across the blocks.
`GRT_ADJUSTMENT` is now 0.15. Detailed routing with it has not been run.

Two other observations from the run:

- The lines in `error.log` from the power-grid step ("Unconnected instance
  u_mem*/VDD!", "Check connectivity failed") appear in every run since the
  first one with memory blocks. The check runs before
  `Project.ExtendPowerStripes`, which is the step that connects the blocks to
  the grid (`src/pdn_cfg.tcl`). They are expected at that point; the final
  layout-versus-schematic check is what confirms the blocks are powered.
- After the 25 passes the router found 40 antenna violations, inserted 44
  diodes and started a second full routing run, as the flow does up to three
  times (`DRT_ANTENNA_REPAIR_ITERS`). The second run starts from the first
  run's wiring.

## Capacity reduction of 15% (17 Nov 2026, second run)

The author's run with `GRT_ADJUSTMENT` 0.15: global routing finished with no
overflow, and the first detailed-routing run ended at 402 violations after 25
passes (still falling slowly: 498, 497, 402, 402). Only 6 were on a memory
block. The other 396 were in one area, x = 570 to 750 um and y = 330 to 520 um,
below the right end of engine 0's block, and 355 of them were Metal2 shorts and
spacing errors between signal wires. With 30% the same area had been clean;
there, the open area was down to 38 violations at pass 24. The likely
reason is placement: routability-driven placement uses the same setting, so at
15% it predicted less congestion and spread the cells less. After the 25
passes, 70 nets had antenna violations; 88 diodes were inserted and the second
routing run stalled at about 1,260.

Change: `GRT_ADJUSTMENT` 0.2. Real flow run locally to the clock tree stage,
then a quick global route: Metal3 overflow 51, nothing across any block.
Whether the dense area clears has not been tested.

## First complete run (17 Nov 2026, capacity reduction 20%)

The flow ran to the end for the first time. Results of its checks:

| Check | Result |
|---|---|
| Detailed routing | 92 violations, unchanged for the last 10 passes of the third routing run |
| Antenna | Passed (65 diodes) |
| KLayout DRC | Passed |
| LVS | Failed: one short, between pins `A_DIN[31]` and `A_BIST_DIN[31]` of engine 0's block (`u_mem0`) |
| Hold | Met in all three corners |
| Setup | Met at typical and fast; slow corner (1.08 V, 125 C) fails by 4.4 ns on 757 paths |
| Clock gates | All 108 connected |

The 92 violations are in one area, x = 630 to 720 um and y = 430 to 590 um,
starting at the pin edge of `u_mem0`; 83 of them are Metal2 shorts and spacing
errors between signal wires. In the global routing of that area Metal2 is at
90 to 97% of the reduced capacity and Metal3 at 91 to 97%. The cell and pin
density there is not higher than elsewhere in the design.

Change: `FP_MACRO_VERTICAL_HALO` 10 (was 0.48), so no cells are placed within
10 um of the edges that carry the blocks' pins. Tested locally to global
routing: overflow 58 (51 without it), nothing across the blocks. A local test
cannot show whether the detailed-routing hotspot clears: the run above reported
almost no global-routing overflow and still left the 92.

Setup at the slow corner: the worst paths start at a memory block. The
512-word block takes 6.8 ns from clock to data at that corner, and the
instruction decode after it does not fit in the remaining 9.9 ns. At the
typical corner every path meets 60 MHz. At the slow corner the limit is
about 47 MHz (1 / (16.66 + 4.41) ns). The 864 "recovery" endpoints in the
report are the resets of the storage latches; the latch endpoints themselves
borrow time by design.

Not examined: 78 maximum-capacitance and 91 maximum-slew warnings at the
typical corner (317 slew at slow), and 255 "illegal overlap" notes from the
extraction step, all between the memory blocks' Metal4 obstruction and Metal4
shapes. The flow does not treat the overlaps as errors.

## First passing layout (18 Nov 2026)

Settings: capacity reduction 20%, 10 um cell-free band along the blocks' pin
edges, antenna repair margin 30%, 40 routing passes. Detailed routing reached
0 violations; two rounds of antenna repair followed. Final checks: routing 0,
antenna 0 (83 diodes), KLayout DRC 0, LVS 0, hold met in all corners, setup
met at the typical and fast corners. The harden still reported failure: the
flow's setup check covers every corner by default, and the slow corner fails
by 4.36 ns on 786 paths (the memory read path described above). The check
runs after the final layout files are written, so the layout itself was
complete.

Decision: `SETUP_VIOLATION_CORNERS` is set to the typical and fast corners.
The chip is specified for 60 MHz at typical conditions and about 47 MHz at
the slow corner (1.08 V, 125 C). Closing the slow corner at 60 MHz would need
a register after the memory read, which adds a tick to every instruction.

## Programs, host software and FPGA build (18 Nov 2026)

With the layout passing, `src/` is frozen: any change to it means a new
harden. The work below changes only programs, tests, host software and the
FPGA build.

| Decision | Reason |
|---|---|
| The USB example is a low-speed device on engine 3 (`programs/usb_ls_device.s`) | Settles the deferred "USB example role". A device can be tested against any computer; the RP2350 runs the protocol above the packets |
| The engine answers within the bus turnaround time by itself (ACK, NAK, prepared data) and reports packets to the host through the RX FIFO, except IN tokens answered with NAK | A host computer repeats a NAKed IN token until the device is ready; reporting each one would fill the 16-byte RX FIFO while the RP2350 is still preparing the answer, and a full FIFO stalls the engine and makes it miss the bus |
| Ethernet transmit on engine 2 (`programs/eth_tx.s`), with the frame written by the host into the spare part of the 512-word block and read with `ldm` | Uses the block for the purpose it was chosen for. The bit chain is unrolled over the eight bit positions and both bit values, so every bit is exactly 6 ticks; the frame check sequence is computed in a pass over the frame before sending |
| `i2c_target.s` keeps its register map in the memory block (`ldm` / `stm`) | Runs on engines with 4 bytes of data memory |
| Divider restart and the attachable buffer (deferred items) will not be added | Both are hardware changes after a passing layout |
| Host software in MicroPython (`firmware/pe_host.py`) with programs assembled on a PC into a module | The assembler is CPython; the board only needs words and label addresses |
| The FPGA build replaces the latch storage with flip-flops and the IHP blocks with block RAM, and reads every other source file unchanged | Latches behind clock gates do not map well onto an FPGA. `fpga/sim_fpga_sources.py` runs the whole-chip tests on exactly that source set |

Ethernet receive was not written. Earlier notes called it impossible at
60 MHz; working through the timing for this write-up gives a narrower
answer. A Manchester receiver must, after each mid-bit transition, ignore the
possible transition at the bit boundary 3 clocks later and catch the next
mid-bit transition 6 clocks later. An engine sees a transition at the first
clock edge after it plus two synchroniser clocks, so between 2 and 3 clocks
after it happens. If the next `wait change` takes its reference level 4
ticks after the previous one ended, that reference falls between 6 and 7
clocks after the transition and reflects the line 4 to 5 clocks after it:
after the boundary transition and before the next mid-bit transition, with
about one clock (16.7 ns) of margin on each side for jitter in the received
edges. That leaves three instruction ticks per bit between waits: one for
`in` (with `feed`, so the checksum unit checks the frame check sequence), and
two that, over a byte, have room for storing the byte with `stm` and the
end-of-frame check. On paper this fits; it has not been written or
simulated, and how much of the margin the jitter of a real cable uses has not
been checked against the standard. The line also needs a receiver outside the
chip (transformer and comparator).

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
