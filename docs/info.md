<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

The design is a programmable protocol emulator. It contains four small
processors, called engines, each running a program from its own memory block
(256 words, or 512 on engine 2). The instruction set is built around reading
pins, writing pins, shifting bits, counting and waiting, and every
instruction takes a known number of clock ticks, so a program is also a
timing diagram. Engines 2 and 3 also have a checksum unit for CRCs of any
width up to 32 bits.

Protocols are programs, not hardware. The examples in `programs/` are UART
transmit and receive, an SPI controller, an I2C controller and target, a
low-speed USB device and a 10BASE-T Ethernet transmitter (5 to 232
instructions). All four engines can run different protocols at once. The
instruction set, the host interface and the pin list are in `docs/spec.md`;
the design and its verification are described in `docs/writeup.md`.

A host loads the programs and exchanges data with the engines over SPI. The
host needs one dedicated pin (host select). While it is high, every other pin
is available to the engines.

The design is specified for a 60 MHz clock at typical conditions. At the
slow process corner (1.08 V, 125 C) its timing allows about 47.5 MHz.

## How to test

The host talks to the chip over SPI (mode 0, at most 1/8 of the chip clock)
while host select (`ui_in[0]`) is low: clock on `ui_in[1]`, data in on
`ui_in[2]`, data out on `uo_out[0]`. `docs/spec.md`, part 2, has the register
map.

On the demo board, the MicroPython driver in `firmware/` does this from the
RP2350. Copy `pe_host.py`, `programs.py` and `demo.py` to the board, select
the design, start a 60 MHz clock, and run:

```python
import demo
chip = demo.run()
```

This reads the chip's ID (0x4A) and size registers, runs a short program on
each engine, and checks the shared flags. `firmware/README.md` shows how to
load a protocol program; in outline:

1. Load a program into an engine's memory and write its settings.
2. Say which engine owns which pins, write the `ENABLE` register, then switch
   the pin drivers on.
3. Exchange data through the engine's FIFO register.

## External hardware

- I2C needs pull-up resistors on the clock and data lines.
- Low-speed USB (D+ on `uio[4]`, D- on `uio[5]`) needs a USB connector, a
  1.5 kohm pull-up from D- to 3.3 V, and series resistors, on a Pmod.
- 10BASE-T Ethernet transmit (TD+ on `uo_out[6]`, TD- on `uo_out[7]`) needs
  a resistor network and an isolating transformer.
- UART works with the demo board's USB serial bridge on `ui_in[3]` and
  `uo_out[4]` with no extra parts.
