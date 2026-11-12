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

Protocols are programs, not hardware. UART, SPI and I2C each fit in 5 to 55
instructions; the programs are in `programs/`. The full instruction set, the
host interface and the pin list are in `docs/spec.md`.

A host loads the programs and exchanges data with the engines over SPI. The
host needs one dedicated pin (host select). While it is high, every other pin
is available to the engines.

## How to test

The host talks to the chip over SPI (mode 0, at most 1/8 of the chip clock)
while host select (`ui_in[0]`) is low: clock on `ui_in[1]`, data in on
`ui_in[2]`, data out on `uo_out[0]`. `docs/spec.md`, part 2, has the register
map.

1. Read address 0x0000: the chip answers 0x4A.
2. Load a program into an engine's memory and write its settings.
3. Say which engine owns which pins, write the `ENABLE` register, then switch
   the pin drivers on.
4. Exchange data through the engine's FIFO register.

`test/host.py` is a model of the host that does all of this, and `test/test.py`
uses it: for example `test_uart_between_engines` loads a UART transmitter into
engine 0 and a receiver into engine 1 and sends bytes from one to the other.

## External hardware

- I2C needs pull-up resistors on the clock and data lines.
- Low-speed USB needs a USB connector and its resistors on a Pmod.
- UART works with the demo board's USB serial bridge on `ui_in[3]` and
  `uo_out[4]` with no extra parts.
