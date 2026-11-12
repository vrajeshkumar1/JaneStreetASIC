; UART receive, 8 data bits, no parity, 1 stop bit.
; Settings: IN_DIR = 0 (lowest bit first), CLKDIV so that 8 ticks = 1 bit.
; Entry point: start.
.define RX in3

good:   push                           ; byte to the host
start:  wait pin RX, 0                 ; falling edge of the start bit
        set r0, 7              [10]    ; move to the middle of data bit 0
bit:    in pin RX, 1
        jmp r0--, bit          [6]
        jbit pin RX, 1, good           ; stop bit must be high
        irq set 0                      ; framing error: shared flag 0 for the host
        wait pin RX, 1                 ; wait for the line to go idle
        jmp start
