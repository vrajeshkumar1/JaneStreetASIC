; UART transmit, 8 data bits, no parity, 1 stop bit.
; Settings: OUT_DIR = 0 (lowest bit first), side-set target 0 = TX pin level,
;           CLKDIV so that 8 ticks = 1 bit (60 MHz, 115200 baud: CLKDIV = 64).
.define TX out4

send:   pull              side 1 [6]   ; stop bit; waits here, line high, while the FIFO is empty
        nop               side 0 [7]   ; start bit
bit:    out pin TX, 1                  ; one data bit
        jmp !osre, bit         [6]     ; repeat until the byte is used up
        jmp send          side 1       ; first tick of the stop bit
