<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

The design is a programmable protocol emulator. It contains four small
processors, called engines. Each engine runs a program of up to 256
instructions from its own memory block. The instruction set is built around
reading pins, writing pins, shifting bits and waiting, and every instruction
takes a known number of clock cycles, so a program is also a timing diagram.

Protocols are programs, not hardware. UART, SPI and I2C each fit in 3 to 53
instructions; the programs are in `programs/`. The full instruction set, the
host interface and the pin list are in `docs/spec.md`.

A host loads the programs and exchanges data with the engines over SPI. The
host needs one dedicated pin (host select). While it is high, every other pin
is available to the engines.

The current source is a probe build that checks the layout flow with one
memory block; see `README.md`.

## How to test

1. Hold host select (`ui_in[0]`) low and load a program and its settings over
   SPI (`docs/spec.md`, part 2).
2. Write the `ENABLE` register to start the engine.
3. Exchange data through the engine's FIFO register.

For the probe build, `test/test.py` shows the command sequence.

## External hardware

- I2C needs pull-up resistors on the clock and data lines.
- Low-speed USB needs a USB connector and its resistors on a Pmod.
- UART works with the demo board's USB serial bridge on `ui_in[3]` and
  `uo_out[4]` with no extra parts.
