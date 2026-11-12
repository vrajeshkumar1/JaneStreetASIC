; SPI controller, mode 0, 8-bit words, both directions at once.
; Settings: OUT_DIR = IN_DIR = 1 (highest bit first), AUTOPULL and AUTOPUSH on
;           with thresholds of 8, side-set target 0 = SCK pin level.
; 4 ticks per bit, so the fastest SPI clock is the chip clock / 4.
; Chip select is driven by the host through a pin write, or by a second
; side-set target.
.define SCK  io3
.define MOSI io1
.define MISO io2

bit:    out pin MOSI, 1   side 0 [1]   ; clock low: put the bit out; waits here when nothing to send
        in pin MISO, 1    side 1       ; clock rises: sample
        jmp bit                        ; clock stays high one more tick
