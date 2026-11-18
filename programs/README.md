# Example programs

Seven protocol programs written for the engine, in the notation of
`docs/spec.md`, section 1.12. Each one is assembled with `tools/pasm.py` and run
in simulation against a model of the other end of the wire: the first five on
one engine (`test/engine/test_protocols.py`) and on the whole chip
(`test/test.py`), the last two on the whole chip. The figures below are
measured in those tests.

| File | Words | Engine | Timing |
|---|---|---|---|
| `uart_tx.s` | 5 | any | 8 ticks per bit, every bit edge on the exact tick |
| `uart_rx.s` | 9 | any | 8 ticks per bit; accepts a sender 2% fast or slow |
| `spi_controller.s` | 5 | any | 4 ticks per bit |
| `i2c_controller.s` | 33 | any | 6 ticks per bit, clock high 3 and low 3 |
| `i2c_target.s` | 58 | any | one tick per clock; tested at 400 kHz |
| `usb_ls_device.s` | 232 | 3 (CRC unit, 16-byte data memory, 16-byte FIFOs) | 40 ticks per bit at 60 MHz (1.5 Mbit/s); every transition it sends on the exact tick; tested with a host 1.5% fast or slow, and works to 4.5% |
| `eth_tx.s` | 129 | 2 (CRC unit, 2 KB memory block) | 6 ticks per bit at 60 MHz (10 Mbit/s); every half-bit change on the exact tick |

Each program starts by setting the pin directions and idle levels it needs,
because pins are inputs at level 0 after reset. The comment block at the top
of each file gives its pins, settings and the format of what it exchanges
with the host.

`i2c_target.s` keeps its 16-byte register map in the spare part of its own
memory block (bytes 1008 to 1023) and reaches it with `ldm` and `stm`, so it
runs on every engine. The host sets the map's starting contents by writing
program memory words 252 to 255 while the engine is stopped.

## USB low speed

`usb_ls_device.s` is the device end of a low-speed USB link. The engine does
the line work: it finds SYNC, recovers the bit clock from the transitions,
undoes NRZI coding and bit stuffing, checks the CRC16 of data packets in the
checksum unit, and answers within the USB turnaround time (ACK to a good data
packet; the prepared packet, or NAK, to an IN token). When sending it adds
SYNC, bit stuffing, NRZI, the CRC16 and the end of packet. Every received
packet goes to the host through the RX FIFO behind a header byte, except IN
tokens answered with NAK, which a host computer repeats until the device is
ready; the host (the RP2350) runs the protocol above that, such as answering
the requests of enumeration, by preparing reply packets in the TX FIFO and
setting shared flag 4. `firmware/pe_host.py` has the host side
(`USBDevice`).

Limits: the CRC5 of tokens is not checked (the checksum unit holds one
polynomial at a time, and it is set for CRC16), the address and endpoint of
a token are not compared, and a bus reset is not reported; the host can see
all three from the packets and pins. The RX FIFO holds exactly a SETUP token
and its 8-byte DATA0 packet with their headers, so the host must empty it
between transactions. The 1.5 kohm pull-up on D- and series resistors are
outside the chip.

## Ethernet

`eth_tx.s` is a 10BASE-T transmitter. The host writes a frame into engine 2's
memory block, pushes its length and sets shared flag 5; the engine computes
the frame check sequence in its checksum unit, then sends preamble,
delimiter, frame and FCS in Manchester code (one bit every 6 clocks), the
TP_IDL pulse, and a link pulse every 16.4 ms while idle. A frame of up to
1,514 bytes fits. Reception is not implemented. Worked through on paper, a
receive loop fits with about one clock of timing margin either side
(`docs/decisions.md`), but it has not been written. The
line needs the usual resistor network and isolating transformer outside the
chip, and the chip clock must be within 0.01% of 60 MHz. `firmware/pe_host.py`
has the host side (`Ethernet`).
