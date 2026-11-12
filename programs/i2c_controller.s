; I2C controller. 6 ticks per bit (CLKDIV = 99 gives 100 kHz at 60 MHz).
; Each "wait pin SCL, 1" takes two ticks when nothing holds the clock low: the
; engine releases the line on the first and sees it high on the second. The
; tick must be at least 4 clocks long for that to hold.
; The host sends each command as the address of a routine below:
;   start, stop, write (followed by the data byte), read, ack, nack.
; write pushes one byte back: 0 = the target acknowledged, 1 = it did not.
; read pushes the byte received; follow it with ack or nack.
; Settings: OUT_DIR = IN_DIR = 1 (highest bit first), side-set target 0 = SCL,
;           SCL and SDA marked open-drain (writing 1 releases the line).
; Not handled: a timeout on a stuck clock, more than one controller on the bus.
; For 400 kHz, rebalance the delays so the clock is low 4 ticks and high 2.
.define SCL io6
.define SDA io7

        set pin SCL, 1                 ; release both lines
        set pin SDA, 1
next:   pull                           ; command = address of a routine below
        mov pc, osr
start:  set pin SDA, 1          [2]    ; release SDA (clock is low on a repeated start)
        wait pin SCL, 1  side 1 [2]    ; release the clock, wait until it is high
        set pin SDA, 0          [2]    ; SDA falls while the clock is high
        jmp next         side 0
stop:   set pin SDA, 0          [2]
        wait pin SCL, 1  side 1 [2]
        set pin SDA, 1          [2]    ; SDA rises while the clock is high
        jmp next
write:  pull                           ; data byte
wbit:   out pin SDA, 1          [1]    ; clock is low: next bit
        wait pin SCL, 1  side 1 [1]    ; clock high; a target holding it low stretches the bit
        jmp !osre, wbit  side 0
        set pin SDA, 1          [1]    ; release SDA for the target's acknowledge
        wait pin SCL, 1  side 1
        in pin SDA, 1                  ; 0 = acknowledged
        push             side 0        ; report it to the host
        jmp next
read:   set pin SDA, 1
        set r0, 7
rbit:   wait pin SCL, 1  side 1
        in pin SDA, 1
        jmp r0--, rbit   side 0 [2]
        push                           ; byte to the host
        jmp next
ack:    set pin SDA, 0          [1]
        jmp clk
nack:   set pin SDA, 1          [1]
clk:    wait pin SCL, 1  side 1 [1]
        jmp next         side 0
