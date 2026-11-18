; 10BASE-T (10 Mbit/s Ethernet) transmitter for engine 2.
;
; The host writes a frame (destination address to the end of the data, at
; least 60 bytes, at most 1,514) into the memory block at byte FRAME (528)
; while the engine is stopped, then pushes its length to the TX FIFO, lowest
; byte first, and sets shared flag 5. The engine computes the frame check sequence (CRC32)
; in its checksum unit and stores it after the frame, then sends preamble,
; start-of-frame delimiter, frame and FCS in Manchester code, ends with the
; TP_IDL pulse, and goes back to sending a link pulse every 16.4 ms.
;
; Pins: TD+ on out6, TD- on out7, driven as complements while sending and both
; low when idle. A 10BASE-T line also needs the usual resistor network and an
; isolating transformer outside the chip.
; Settings: CLKDIV = 0 (one tick per clock, so 3 ticks per half bit at 60 MHz),
;           OUT_DIR = 0 (lowest bit first), SIDE0 = out6 level,
;           SIDE1 = out7 level (side 1 = high, 2 = low, 0 = idle),
;           checksum direction 0, polynomial 0xEDB88320, width 32.
;
; Timing: one bit every 6 ticks, the line changing at every half bit (t0 and
; t3) by side-set. The bit chain below is unrolled over the eight bit
; positions of a byte and over the two values of each bit, so that every path
; from one bit to the next is exactly 6 ticks with no jump on the critical
; path except the choice of the next bit's block. The work of fetching bytes
; is spread over the spare ticks of bits 0, 1, 2 and 6.
;
; Registers: r0 link pulse counter, r1 byte address, r2 next byte, r3 bytes
; left after the current one, r4 scratch, r5 FCS, r6 preamble counter,
; r7 0xFFFF (timeout).

.define FRAME 528                    ; word 132: 1,520 bytes for frame and FCS
.define NLP_WAITS 14                 ; link pulse after 15 waits of 65,536 ticks

idle:   nop side 0                   ; both lines low
        set r7, 0xFFFF
nlp:    set r0, NLP_WAITS
nwait:  wait flag 5, 1, timeout r7
        jmp !t, send                 ; the host has a frame ready
        jmp r0--, nwait
        nop side 1 [5]               ; link pulse: 100 ns high
        nop side 0
        jmp nlp

send:   irq clear 5
        pull
        mov r3, osr                  ; frame length, low byte
        pull
        mov r4, osr
        shl r4, r4, 8
        or r3, r3, r4                ; frame length
        mov crc_lo, null, inv        ; CRC32 starts at 0xFFFFFFFF
        mov crc_hi, null, inv
        set r1, FRAME
        sub r4, r3, 1
crcl:   ldm r2, [r1]
        mov osr, r2
        set r6, 7
crcb:   out null, 1, feed            ; one bit through the checksum unit
        jmp r6--, crcb
        add r1, r1, 1
        jmp r4--, crcl
        mov r5, crc_lo, inv          ; FCS, lowest byte first, after the frame
        stm r5, [r1]
        add r1, r1, 1
        shr r5, r5, 8
        stm r5, [r1]
        add r1, r1, 1
        mov r5, crc_hi, inv
        stm r5, [r1]
        add r1, r1, 1
        shr r5, r5, 8
        stm r5, [r1]

        add r3, r3, 3                ; bytes after the first, FCS included
        add r3, r3, 1                ; (counted down once at bit 2 of each byte)
        set r1, FRAME
        ldm r2, [r1]                 ; first byte
        add r1, r1, 1
        set r6, 30
; Preamble (7 x 0x55) and start-of-frame delimiter (0xD5): 31 pairs of bits
; 1, 0 and then 1, 1. In half bits: low 3 ticks, then (high 6, low 6) 31 times,
; high 3, low 3, high 3.
        nop side 2 [2]
pl:     nop side 1 [5]
        jmp r6--, pl side 2 [5]
        nop side 1 [2]
        nop side 2 [2]
        mov osr, r2 side 1           ; t3 of the last delimiter bit
        out t, 1                     ; t4: bit 0 of the first byte
        jmp t, o0                    ; t5
; Bit chain. zK / oK send bit K of a byte when it is 0 / 1: first half at
; t0, second half at t3. Each block fetches the next bit at t0 and chooses
; the next block at t5; one choice falls through to the next line.
z0:     out t, 1 side 1
        ldm r2, [r1]
        nop side 2 [1]
        jmp !t, z1
o1:     out t, 1 side 2
        add r1, r1, 1 [1]
        nop side 1 [1]
        jmp t, o2
z2:     out t, 1 side 1
        sub r3, r3, 1 [1]
        nop side 2 [1]
        jmp !t, z3
o3:     out t, 1 side 2
        nop [1]
        nop side 1 [1]
        jmp t, o4
z4:     out t, 1 side 1
        nop [1]
        nop side 2 [1]
        jmp !t, z5
o5:     out t, 1 side 2
        nop [1]
        nop side 1 [1]
        jmp t, o6
z6:     out t, 1 side 1
        mov osr, r2 [1]
        nop side 2 [1]
        jmp !t, z7
o7:     out t, 1 side 2
        nop
        jmp !r3, last1
        nop side 1
        jmp t, o0e
        jmp z0
o0e:    nop                          ; t5: early entry to o0
o0:     out t, 1 side 2
        ldm r2, [r1]
        nop side 1 [1]
        jmp t, o1
z1:     out t, 1 side 1
        add r1, r1, 1 [1]
        nop side 2 [1]
        jmp !t, z2
o2:     out t, 1 side 2
        sub r3, r3, 1 [1]
        nop side 1 [1]
        jmp t, o3
z3:     out t, 1 side 1
        nop [1]
        nop side 2 [1]
        jmp !t, z4
o4:     out t, 1 side 2
        nop [1]
        nop side 1 [1]
        jmp t, o5
z5:     out t, 1 side 1
        nop [1]
        nop side 2 [1]
        jmp !t, z6
o6:     out t, 1 side 2
        mov osr, r2 [1]
        nop side 1 [1]
        jmp t, o7
z7:     out t, 1 side 1
        nop
        jmp !r3, last0
        nop side 2
        jmp t, o0e
        jmp z0
; End of frame: finish the last bit, then TP_IDL (high for 300 ns more), then
; idle and link pulses again.
last0:  nop side 2 [2]               ; t3 .. t5
        nop side 1 [15]              ; TP_IDL
        nop [1]
        jmp idle
last1:  nop side 1 [2]
        nop side 1 [15]
        nop [1]
        jmp idle
