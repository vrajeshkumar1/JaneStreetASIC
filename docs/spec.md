# Specification v0.2

Status: part 1 is implemented in `src/pe_engine.sv` and tested. Part 2 (the host
interface) is not implemented yet. Part 1 is the instruction set, part 2 the
host interface, part 3 the pins. Where a rule was chosen without a requirement
behind it, `docs/decisions.md` says so.

Terms used throughout:

- **Engine**: one small processor that runs one protocol program. The chip has
  four (a build parameter).
- **Clock**: the 60 MHz chip clock.
- **Tick**: the engine's time step. One tick is `CLKDIV + 1` clocks, where
  `CLKDIV` is a per-engine 16-bit setting. Every instruction takes a whole
  number of ticks.
- **Host**: whatever programs the chip over SPI. On the Tiny Tapeout demo board
  that is the RP2350 running MicroPython.
- **Stall**: an instruction that cannot complete yet (for example a pull from an
  empty FIFO) repeats on the next tick. The program counter does not move.

---

## Part 1. Instruction set

### 1.1 What each engine holds

| Name | Width | Purpose |
|---|---|---|
| `r0`..`r7` | 16 bits each | General registers |
| `isr` | 8 bits + a 4-bit count | Input shift register: bits arriving from a pin collect here |
| `osr` | 8 bits + a 4-bit count | Output shift register: a byte being sent leaves from here |
| `pc` | 9 bits | Program counter (8 bits are used with a 256-word memory) |
| `lr` | 9 bits | Link register: return address written by `call` |
| `T` | 1 bit | Test flag. Conditional execution looks only at this flag |
| `Z`, `C` | 1 bit each | Equal and less-than results of the last `cmp` |
| `wtime` | 16 bits | Ticks the most recent `wait` spent stalled (stops at 0xFFFF) |
| `crc` | 32 bits | Checksum register (section 1.8) |
| TX FIFO | 16 bytes | Host to engine |
| RX FIFO | 16 bytes | Engine to host |
| Data memory | 16 bytes | Addressed by `ld` and `st`; the host can read and write it |

All engines share eight one-bit flags, `F0`..`F7`, used to signal each other and
the host.

Each engine has its own 256-word program memory (one IHP 256 x 32 memory block).

### 1.2 Timing rules

1. An instruction that does not stall takes exactly one tick, plus its delay.
2. A stalled instruction repeats each tick until it can complete. Its delay
   starts after it completes.
3. Side-set (section 1.4) is applied on the first tick of the instruction, even
   if the instruction then stalls.
4. A jump, call or return takes one tick whether or not it is taken.
5. A skipped instruction (condition false, section 1.3) takes one tick plus its
   delay, applies its side-set, never stalls, and changes nothing else.
6. Pin outputs are registered. A pin written during tick *n* changes at the
   start of tick *n + 1*.
7. Pin inputs pass through two flip-flops, so an engine sees a pin two clocks
   late. With the pad delays, an engine reading back its own output sees it
   roughly three clocks after it changed. A `wait` on a line the same
   instruction has just released by side-set therefore always stalls for at
   least one tick.
8. Pin levels and directions are zero after reset. A program sets the
   directions and idle levels it needs in its first instructions.

### 1.3 Instruction word

Every instruction is one 32-bit word.

| Bits | Field | Meaning |
|---|---|---|
| 31:28 | opcode | Section 1.5 |
| 27:26 | condition | `00` always, `01` only if `T` = 1 (`ift`), `10` only if `T` = 0 (`ifn`), `11` illegal |
| 25:22 | delay | Extra ticks after the instruction completes, 0 to 15 |
| 21 | side-set enable | 1 = apply the side-set value |
| 20:19 | side-set value | Bit 19 goes to side-set target 0, bit 20 to target 1 |
| 18:0 | operands | Depends on the opcode |

### 1.4 Side-set

Side-set changes up to two pins at the same moment as any instruction, without
using an instruction of its own. Each engine has two side-set targets, set by
the host (`SIDE0`, `SIDE1` in part 2). A target names one writable pin and says
whether the bit sets the pin's level or its direction. A target that is not
enabled ignores its bit.

If side-set and the instruction itself write the same pin on the same tick,
side-set wins.

### 1.5 Opcodes

Operand bit positions are within bits 18:0. Unlisted bits must be zero.

| Op | Name | Operand fields | What it does |
|---|---|---|---|
| 0 | `jmp` | 18 mode, 17:14 test, 13:11 reg, 8:0 target | mode 0: jump to target if the test (section 1.6) is true. mode 1 (`tst`): `T` <- the test result, no jump |
| 1 | `jbit` | 18 mode, 17 source, 16:14 reg, 13:10 bit, 9 value, 8:0 target | source 0: readable pin number `bit`. source 1: bit `bit` of `reg`. mode 0: jump if the bit equals `value`. mode 1 (`tbit`): `T` <- (bit equals `value`) |
| 2 | `wait` | 18:17 kind, 16 value, 15:12 A, 11:8 B, 7 timeout enable, 6:4 timeout reg | kind 0: stall until readable pin A equals `value`. kind 1 (`wait change`): stall until pin A or pin B differs from what it was on the instruction's first tick, so it always takes at least two ticks. kind 2: stall until shared flag A equals `value`. With timeout enabled the wait also ends once it has stalled for `timeout reg` ticks; then `T` <- 1 if it timed out, 0 if not. `wtime` records the ticks spent stalled |
| 3 | `in` | 18:17 source, 16:13 pin or reg, 12:10 n-1, 9 feed | Shift n bits (1 to 8) into `isr`. source 0: a readable pin. 1: `T`. 2: the low n bits of a register. 3: zeros. A pin or `T` takes n = 1. `feed` = 1 also passes the bit to the checksum unit, and needs n = 1 |
| 4 | `out` | 18:17 dest, 16:13 pin or reg, 12:10 n-1, 9 feed | Shift n bits (1 to 8) out of `osr`. dest 0: a writable pin. 1: `T`. 2: a register (zero-extended). 3: discard. A pin or `T` takes n = 1. `feed` as for `in` |
| 5 | `push` / `pull` | 18 direction, 17 block, 16 only-if | direction 0 `push`: RX FIFO <- `isr`, then clear `isr`. direction 1 `pull`: `osr` <- TX FIFO. block 1: stall while the FIFO is full (push) or empty (pull). only-if 1: push only when `isr` holds at least the push threshold; pull only when `osr` is empty |
| 6 | `mov` | 18:14 dest, 13:12 operation, 11:7 source | Copy between the places in section 1.7. operation 0 copy, 1 invert, 2 reverse the low 8 bits, 3 parity: `T` <- XOR of all source bits, and the value is copied unchanged |
| 7 | `irq` | 18:17 operation, 16:14 flag | 0 set the shared flag, 1 clear it, 2 set it and stall until something clears it |
| 8 | `set` | 18:16 reg, 15:0 value | reg <- 16-bit value |
| 9 | ALU, register | 18:16 function, 15:13 rd, 12:10 ra, 9:7 rb | rd <- ra (function) rb |
| 10 | ALU, immediate | 18:16 function, 15:13 rd, 12:10 ra, 9:0 value | rd <- ra (function) value, value zero-extended |
| 11 | `ld` | 18:16 rd, 15 use base, 14:12 base reg, 11:8 offset | rd <- data memory[(base + offset) mod 16], zero-extended |
| 12 | `st` | 18:16 rs, 15 use base, 14:12 base reg, 11:8 offset | data memory[(base + offset) mod 16] <- low byte of rs |
| 13 | `call` / `ret` | 18 which, 8:0 target | which 0 `call`: `lr` <- `pc` + 1, jump to target. which 1 `ret`: jump to `lr` |
| 14 | pin | 18:17 operation, 16:13 pin, 12 value | 0 `set pin`: level <- value. 1 `toggle pin`: invert the level. 2 `set dir`: direction <- value (1 = output; bidirectional pins only) |
| 15 | `halt` | none | Stop this engine and set its HALTED status bit |

ALU functions: 0 `add`, 1 `sub`, 2 `and`, 3 `or`, 4 `xor`, 5 `shl`, 6 `shr`,
7 `cmp`. Shifts are logical and use the low 4 bits of the second operand.
`cmp` writes no register; it sets `Z` = (ra equals operand) and `C` = (ra is
less than operand, unsigned). No other instruction changes `Z` or `C`.

`nop` is `mov null, null`.

An illegal word (condition `11`, or a reserved kind, source or operation code)
behaves as `halt` and also sets the ILLEGAL status bit.

### 1.6 Jump tests

| Code | Written as | True when |
|---|---|---|
| 0 | (none) | Always |
| 1 | `!rN` | Register N is zero |
| 2 | `rN--` | Register N is not zero. The register is then decremented either way |
| 3 | `rN` | Register N is not zero |
| 4 | `eq` | `Z` = 1 |
| 5 | `ne` | `Z` = 0 |
| 6 | `lt` | `C` = 1 |
| 7 | `ge` | `C` = 0 |
| 8 | `T` | `T` = 1 |
| 9 | `!T` | `T` = 0 |
| 10 | `!osre` | `osr` still holds unsent bits |
| 11 | `osre` | `osr` is empty |
| 12 | `txempty` | TX FIFO is empty |
| 13 | `!txempty` | TX FIFO holds at least one byte |
| 14 | `rxfull` | RX FIFO is full |
| 15 | `!rxfull` | RX FIFO has room |

Every test reads stored bits only, so the jump decision does not wait for the
adder.

### 1.7 `mov` sources and destinations

| Code | As a source | As a destination |
|---|---|---|
| 0..7 | `r0`..`r7` | `r0`..`r7` |
| 8 | `isr` | `isr` (its count becomes 8) |
| 9 | `osr` | `osr` (marked full) |
| 10 | `pins_in`: the eight input pins | `pins_out`: the eight output pins |
| 11 | `pins_io`: the eight bidirectional pins | `pins_io`: levels of the bidirectional pins |
| 12 | `wtime` | `dir_io`: directions of the bidirectional pins |
| 13 | `crc_lo`: checksum bits 15:0 | `crc_lo` |
| 14 | `crc_hi`: checksum bits 31:16 | `crc_hi` |
| 15 | `null`: zero | `null`: discard |
| 16 | `lr` | `lr` |
| 17 | `pc` | `pc`: a computed jump |
| 18 | `status`: bit 0 TX empty, 1 TX full, 2 RX empty, 3 RX full, 7:4 TX level low bits | reserved |
| 19 | `flags`: the eight shared flags | reserved |
| 20..31 | reserved | reserved |

A write to `pins_out`, `pins_io` or `dir_io` changes only the pins this engine
owns (part 2, pin ownership).

### 1.8 Checksum unit

A 32-bit shift register with feedback, for cyclic redundancy checks of any width
up to 32. The host sets the polynomial, the width and the direction. Each bit
that passes through a one-bit `in` or `out` whose `feed` bit is 1 advances it by
one step. The program reads and writes the value through `crc_lo` and `crc_hi`.

- Direction 0 (lowest bit first): `fb = crc[0] xor bit; crc = (crc >> 1) xor (fb ? poly : 0)`.
  This is the form used by USB, Ethernet, Modbus and 1-Wire, with the
  polynomial written bit-reversed.
- Direction 1 (highest bit first): `fb = crc[width-1] xor bit; crc = ((crc << 1) xor (fb ? poly : 0))`
  masked to `width` bits. This is the form used by CAN, SD cards and SMBus.

### 1.9 Pin numbers

One-pin instructions carry a 4-bit pin number. Reading and writing use the same
numbers for different physical pins on 0 to 7:

| Number | Read by `wait`, `jbit`, `in` | Written by `out`, pin instructions, side-set |
|---|---|---|
| 0..7 | Input pin `in0`..`in7` (`ui_in`) | Output pin `out0`..`out7` (`uo_out`) |
| 8..15 | Bidirectional pin `io0`..`io7` (`uio_in`) | Bidirectional pin `io0`..`io7` (`uio_out`, `uio_oe`) |

An engine can read any pin. It can write only pins it owns.

Open-drain: a bidirectional pin marked open-drain by the host is never driven
high. Writing level 1 releases the pin (direction input); writing level 0
drives it low. Side-set and `out` follow the same rule.

### 1.10 Automatic load and store

Per-engine settings `AUTOPULL`, `AUTOPUSH`, and thresholds of 1 to 8 bits.

- `osr` is empty when its output count has reached the pull threshold.
- Automatic load: at the end of an `out` that empties `osr`, if the TX FIFO
  holds a byte, `osr` is reloaded on that same tick. If the FIFO is empty,
  `osr` stays empty. A later `out` that finds `osr` empty stalls until a byte
  arrives; the byte is loaded on one tick and the `out` runs on the next.
- Automatic store: at the end of an `in` that brings the input count up to the
  push threshold, `isr` is pushed to the RX FIFO and cleared on that same tick.
  If the RX FIFO is full, the `in` stalls after shifting until there is room.

### 1.11 Shift direction

Per-engine settings `OUT_DIR` and `IN_DIR`. 0 = lowest bit first (shift right),
1 = highest bit first (shift left). With highest-bit-first input, a single
shifted-in bit lands in bit 0.

### 1.12 Assembler notation

```
label:  [ift|ifn] mnemonic operands   [side V] [[N]]   ; comment
```

`side V` is the side-set value (0 to 3) and `[N]` the delay. Pin operands are
written `in0`..`in7`, `out0`..`out7`, `io0`..`io7`, or a name given with
`.define`. Memory operands are `[rN]`, `[rN+offset]` or `[@offset]`. The
assembler is `tools/pasm.py`; its source lists every operand form. The programs
in `programs/` use this notation.

---

## Part 2. Host interface

### 2.1 Electrical

SPI mode 0 (clock idles low, data sampled on the rising edge), highest bit
first. The chip samples the SPI clock with its own clock, so the SPI clock must
be at most one sixth of the chip clock: 10 MHz at 60 MHz.

| Signal | Pin | Notes |
|---|---|---|
| Host select, active low | `ui_in[0]` | The only pin the host owns permanently |
| SPI clock | `ui_in[1]` | Only while host select is low |
| Data, host to chip | `ui_in[2]` | Only while host select is low |
| Data, chip to host | `uo_out[0]` | Only while host select is low |

While host select is low, engines keep running. They see `in1` and `in2` frozen
at their last value, and `out0` carries host data. When host select returns
high, the three pins are ordinary pins again.

### 2.2 Transfer format

```
write:  [1 a14..a8] [a7..a0] [data] [data] ...
read:   [0 a14..a8] [a7..a0] [dummy] [data] [data] ...
```

The first bit is 1 for a write. The address is 15 bits. After each data byte
the address goes up by one, except at a FIFO address, where every byte is one
push or pop. A read has one dummy byte after the address so the chip has time
to fetch the first data byte. Raising host select ends the transfer.

### 2.3 Address map

| Address | Contents |
|---|---|
| 0x0000..0x003F | Global registers (2.4) |
| 0x0100 + 0x40 x e | Registers of engine e (2.5) |
| 0x0200 + 0x10 x e | Data memory of engine e, 16 bytes |
| 0x1000 + 0x400 x e | Program memory of engine e: 256 words, 4 bytes each, lowest byte first. A word is stored when its fourth byte arrives. Accessible only while the engine is stopped |

### 2.4 Global registers

| Address | Name | Access | Contents |
|---|---|---|---|
| 0x00 | `ID` | read | 0x4A |
| 0x01 | `VERSION` | read | Specification version, 0x01 |
| 0x02 | `ENABLE` | read/write | Bit e = engine e runs. All bits of one write take effect on the same clock edge |
| 0x03 | `RESTART` | write | Bit e = 1: reset engine e's program counter, shift registers, flags and FIFOs. Clears itself |
| 0x04 | `FLAGS` | read | The eight shared flags |
| 0x05 | `FLAGS_SET` | write | Writing 1 sets that flag |
| 0x06 | `FLAGS_CLR` | write | Writing 1 clears that flag |
| 0x07 | `ATTN_MASK` | read/write | Bits 3:0: shared flags 0..3 raise attention. Bits 7:4: engine e halted raises attention |
| 0x08 | `CTRL` | read/write | Bit 0: `out0` is the attention line while host select is high. Bit 1: lock, ignore host select until the next reset |
| 0x09 | `STATUS` | read | Bits 3:0: engine e halted. Bits 7:4: engine e stalled |
| 0x10, 0x11 | `OWNER_OUT` | read/write | Two bits per output pin: which engine owns `out0`..`out7` |
| 0x12, 0x13 | `OWNER_IO` | read/write | Two bits per bidirectional pin |
| 0x14 | `DRIVE_OUT` | read/write | Bit n = 1: `out n` is driven by its owner. 0: held low |
| 0x15 | `DRIVE_IO` | read/write | Bit n = 1: `io n` is controlled by its owner. 0: input |
| 0x16 | `OPEN_DRAIN` | read/write | Bit n = 1: `io n` is open-drain |

### 2.5 Engine registers

Offsets from the engine's base address.

| Offset | Name | Access | Contents |
|---|---|---|---|
| 0x00 | `CFG` | read/write | Bit 0 `OUT_DIR`, 1 `IN_DIR`, 2 `AUTOPULL`, 3 `AUTOPUSH`, 4 checksum direction |
| 0x01 | `PULL_THRESH` | read/write | 1 to 8 |
| 0x02 | `PUSH_THRESH` | read/write | 1 to 8 |
| 0x03, 0x04 | `CLKDIV` | read/write | Tick length is `CLKDIV + 1` clocks |
| 0x05 | `SIDE0` | read/write | Bits 3:0 writable pin number, bit 4 enable, bit 5: 1 = direction, 0 = level |
| 0x06 | `SIDE1` | read/write | As `SIDE0` |
| 0x07, 0x08 | `PC` | read/write | Program counter. Writable while the engine is stopped |
| 0x09 | `STATUS` | read | Bit 0 running, 1 stalled, 2 halted, 3 illegal instruction, 4 TX empty, 5 TX full, 6 RX empty, 7 RX full |
| 0x0A | `TX_LEVEL` | read | Bytes in the TX FIFO |
| 0x0B | `RX_LEVEL` | read | Bytes in the RX FIFO |
| 0x0C | `FIFO` | read/write | Write pushes to the TX FIFO. Read pops from the RX FIFO. The address does not advance |
| 0x0D | `DEBUG` | read, write 1 to clear | Bit 0: host wrote to a full TX FIFO. 1: host read an empty RX FIFO. 2: non-blocking pull found the FIFO empty. 3: non-blocking push found it full |
| 0x0E..0x11 | `CRC_POLY` | read/write | Checksum polynomial, lowest byte first |
| 0x12 | `CRC_WIDTH` | read/write | 1 to 32 (used by direction 1) |
| 0x14..0x17 | `CRC` | read | Current checksum value |
| 0x20..0x2F | `R0`..`R7` | read/write | The registers, two bytes each, lowest byte first. Writable while the engine is stopped |

### 2.6 After reset

All engines are stopped, every pin is an input or held low, and program memory
contents are undefined. The host loads programs and settings, then writes
`ENABLE`. A design that is deselected on the demo board loses power, so this
sequence is repeated every time it is selected.

---

## Part 3. Pins

| Tile pin | Name | Use |
|---|---|---|
| `ui_in[0]` | `HOST_SEL_N` | Host select, active low. Reserved |
| `ui_in[1]` | `in1` | Protocol input. SPI clock while host select is low |
| `ui_in[2]` | `in2` | Protocol input. SPI data in while host select is low |
| `ui_in[3]` | `in3` | Protocol input. The demo board bridges this pin to USB serial as data into the chip |
| `ui_in[4..7]` | `in4`..`in7` | Protocol inputs |
| `uo_out[0]` | `out0` | Protocol output. SPI data out while host select is low. Optional attention line |
| `uo_out[1..3]` | `out1`..`out3` | Protocol outputs |
| `uo_out[4]` | `out4` | Protocol output. The demo board bridges this pin to USB serial as data out of the chip |
| `uo_out[5..7]` | `out5`..`out7` | Protocol outputs |
| `uio[0..7]` | `io0`..`io7` | Protocol pins, direction set per pin. `io0`..`io3` and `io4`..`io7` each match one row of a Pmod connector |

Suggested protocol placement, following Tiny Tapeout's recommended pinouts:
SPI on `io0`..`io3` (chip select, data out, data in, clock), I2C on `io6`
(clock) and `io7` (data), UART on `in3` and `out4`.
