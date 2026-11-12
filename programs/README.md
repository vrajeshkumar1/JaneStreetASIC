# Example programs (drafts)

These five programs were written on paper to test the instruction set before
any hardware existed. They use the notation in `docs/spec.md`, section 1.12.
They have not been assembled or simulated yet; that happens when the assembler
and the first engine exist.

| File | Instructions | Registers used | Ticks per bit |
|---|---|---|---|
| `uart_tx.s` | 5 | 0 | 8 |
| `uart_rx.s` | 9 | 1 | 8 |
| `spi_controller.s` | 3 | 0 | 4 |
| `i2c_controller.s` | 31 | 1 | 6 |
| `i2c_target.s` | 53 | 5 | runs at full clock speed |
