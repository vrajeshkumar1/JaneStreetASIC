# Example programs

Five protocols written for the engine, in the notation of `docs/spec.md`,
section 1.12. Each one is assembled with `tools/pasm.py` and run in simulation
against a model of the other end of the wire, on one engine
(`test/engine/test_protocols.py`) and with four running at once on the whole
chip (`test/test.py`).
The figures below are measured in those tests.

| File | Instructions | Registers used | Timing |
|---|---|---|---|
| `uart_tx.s` | 5 | 0 | 8 ticks per bit, every bit edge on the exact tick |
| `uart_rx.s` | 9 | 1 | 8 ticks per bit; accepts a sender 2% fast or slow |
| `spi_controller.s` | 5 | 0 | 4 ticks per bit |
| `i2c_controller.s` | 33 | 1 | 6 ticks per bit, clock high 3 and low 3 |
| `i2c_target.s` | 55 | 5 | one tick per clock; tested at 400 kHz |

Each program starts by setting the pin directions and idle levels it needs,
because pins are inputs at level 0 after reset.
