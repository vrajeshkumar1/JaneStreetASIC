; I2C target with a 16-byte register map held in the engine's data memory.
; Write transfer: address, register pointer, then data bytes (pointer advances).
; Read transfer: address, then data bytes from the pointer (pointer advances).
; Settings: CLKDIV = 0 (one tick per clock), OUT_DIR = IN_DIR = 1,
;           SCL and SDA marked open-drain.
; The host writes (device address << 1) to r7 before starting the engine.
; Registers: r0 bit counter, r2 register pointer, r3 byte, r4 scratch, r7 address.
; Entry point: idle.
.define SCL io6
.define SDA io7

idle:   wait pin SDA, 1
        wait pin SDA, 0
        jbit pin SCL, 0, idle        ; SDA fell with the clock low: ordinary data
start:  wait pin SCL, 0
        call rbyte                   ; address byte
        mov r3, isr
        and r4, r3, 0xFE
        cmp r4, r7
        jmp ne, idle                 ; not this device
        call ack
        jbit r3.0, 1, rd             ; read/write bit set: controller wants to read
        call rbyte                   ; first written byte = register pointer
        mov r2, isr
        call ack
wr:     call rbyte                   ; leaves via idle or start on a stop or repeated start
        mov r3, isr
        st r3, [r2]
        add r2, r2, 1
        and r2, r2, 15
        call ack
        jmp wr
rd:     ld r3, [r2]
        add r2, r2, 1
        and r2, r2, 15
        mov osr, r3
        call tbyte
        wait pin SCL, 1              ; controller's acknowledge bit
        jbit pin SDA, 1, idle        ; not acknowledged: controller has finished
        wait pin SCL, 0
        jmp rd

rbyte:  set r0, 7
        wait pin SCL, 1
        in pin SDA, 1
        wait change SCL, SDA         ; whichever line moves first
        jbit pin SCL, 0, rnext       ; clock fell: ordinary bit
        jbit pin SDA, 0, start       ; SDA fell with the clock high: repeated start
        jmp idle                     ; SDA rose with the clock high: stop
rbit:   wait pin SCL, 1
        in pin SDA, 1
        wait pin SCL, 0
rnext:  jmp r0--, rbit
        ret

ack:    set pin SDA, 0               ; clock is low: pull SDA low
        wait pin SCL, 1
        wait pin SCL, 0
        set pin SDA, 1
        ret

tbyte:  out pin SDA, 1               ; clock is low: next bit
        wait pin SCL, 1
        wait pin SCL, 0
        jmp !osre, tbyte
        set pin SDA, 1               ; release for the controller's acknowledge
        ret
