; USB low-speed (1.5 Mbit/s) device-side transceiver for engine 3.
;
; The engine does the line work: it finds the SYNC pattern, recovers the
; bit clock from the transitions, undoes NRZI coding and bit stuffing, checks
; the CRC16 of data packets in the checksum unit, recognises the end of a
; packet, and answers within the USB turnaround time: ACK to a data packet
; with a correct CRC, the prepared packet (or NAK) to an IN token. When it
; sends, it adds SYNC, bit stuffing, NRZI coding, the CRC16 and the end of
; packet. The host (the RP2350) does the protocol above that: it reads every
; received packet from the RX FIFO, and prepares replies in the TX FIFO.
;
; Pins: D+ on io4, D- on io5 (both owned by this engine, push-pull). The 1.5 kohm
; pull-up on D- that marks a low-speed device is outside the chip.
; Settings: CLKDIV = 0 (one tick per clock, 40 ticks per bit at 60 MHz),
;           OUT_DIR = IN_DIR = 0, no automatic push or pull,
;           SIDE0 = io4 level, SIDE1 = io5 level (side 2 = J, 1 = K, 0 = SE0),
;           checksum direction 0, polynomial 0xA001 (CRC16, bit-reversed).
;
; Received packet, in the RX FIFO: one header byte, then the packet's bytes
; from the PID onwards (at most 16). Header bits 4:0: number of bytes; bit 7:
; the CRC16 check passed (meaningful for DATA0 / DATA1 only). Every packet is
; reported except an IN token answered with NAK: a host computer repeats such
; tokens until the device is ready, and reporting each one would fill the RX
; FIFO while the host is still preparing the answer.
; Packet to send, in the TX FIFO: one header byte, then the PID and the data.
; Header bits 3:0: number of bytes from the PID onwards; bit 7: append CRC16.
; The host writes it, then sets shared flag 4. The engine sends it in answer to
; the next IN token and clears flag 4; until then it answers IN with NAK.
;
; Timing, in clocks after a transition is seen (E) or after the line was
; sampled as unchanged (X, 13 clocks after the expected edge): every path
; reaches the next wait at a fixed time (E+20, X+5 or X+13), and each of the
; three waits has its own timeout register so that a missing edge is noticed
; 53 clocks after the last one. A transition is accepted from 14 clocks early
; to 13 clocks late.
;
; Registers while receiving: r0, r5, r6 the three timeouts, r1 count of ones
; left before a stuffed bit, r2 bits left in the byte, r3 scratch,
; r4 header (byte count, bit 7 CRC passed).
; While sending: r0 end flag, r1 ones count, r2 bits left in the byte,
; r3 FIFO bytes left, r5 CRC bytes left, r6 PID or CRC, r7 phase
; (2 SYNC, 1 PID, 0 data). r4 is kept for the report.

.define DP io4
.define DM io5
.define TO_A 32                      ; timeout after a transition
.define TO_B 35                      ; timeout after an unchanged bit
.define TO_C 26                      ; timeout after an unchanged bit that ended a byte

; ---------------------------------------------------------------- receive
idle:   set r5, TO_A
        set r6, TO_B
        set r0, TO_C
        wait pin DP, 0               ; idle (J) or end of a previous packet
        wait pin DP, 1               ; E: J to K, the first SYNC transition
        nop [15]                     ; E+1 .. E+16
        nop [1]                      ; E+17 .. E+18
        jmp syncw                    ; E+19
sedge:  nop [15]                     ; E+2 .. E+17
        nop                          ; E+18
        jmp syncw                    ; E+19
syncw:  wait change DP, DM, timeout r5   ; first tick at E+20
        jmp !t, sedge                ; a transition: still in SYNC
        set r1, 5                    ; no transition: the 1 that ends SYNC
        set r2, 7
        set r4, 0 [8]
        jmp rxwC                     ; first tick of rxwC 13 ticks after X

rxwA:   wait change DP, DM, timeout r5
        jmp !t, edge
        jmp one
rxwC:   wait change DP, DM, timeout r0
        jmp !t, edge
        jmp one
rxwB:   wait change DP, DM, timeout r6
        jmp !t, edge
one:    in t, 1, feed                ; X+2: a 1 (T = 1 after a timeout)
        sub r1, r1, 1                ; X+3
        jmp r2--, rxwB               ; X+4
        mov r3, isr                  ; X+5: byte complete
        st r3, [r4]                  ; X+6
        set r2, 7                    ; X+7
        jmp !r4, pidB                ; X+8
        nop [1]                      ; X+9 .. X+10
        add r4, r4, 1                ; X+11
        jmp rxwC                     ; X+12
pidB:   mov crc_lo, null, inv        ; X+9: PID done, start the CRC16 at 0xFFFF
        mov crc_hi, null             ; X+10
        add r4, r4, 1                ; X+11
        jmp rxwC                     ; X+12

edge:   nop [2]                      ; E+2 .. E+4: both lines settle
        mov r3, pins_io              ; E+5
        and r3, r3, 0x30             ; E+6
        jmp !r3, eop                 ; E+7: both low, end of packet
        jmp !r1, stuffed             ; E+8: six ones before: a stuffed bit
        in t, 1, feed                ; E+9: a 0 (T = 0 after a transition)
        set r1, 6                    ; E+10
        jmp r2--, padA               ; E+11
        mov r3, isr                  ; E+12: byte complete
        st r3, [r4]                  ; E+13
        set r2, 7                    ; E+14
        jmp !r4, pidA                ; E+15
        nop [1]                      ; E+16 .. E+17
        add r4, r4, 1                ; E+18
        jmp rxwA                     ; E+19
pidA:   mov crc_lo, null, inv        ; E+16
        mov crc_hi, null             ; E+17
        add r4, r4, 1                ; E+18
        jmp rxwA                     ; E+19
padA:   nop [6]                      ; E+12 .. E+18
        jmp rxwA                     ; E+19
stuffed: set r1, 6 [9]               ; E+9 .. E+18
        jmp rxwA                     ; E+19

; ------------------------------------------------------ end of packet
eop:    wait pin DM, 1               ; J: end of the end-of-packet
        mov r7, crc_lo
        set r3, 0xB001               ; CRC16 residue of a correct packet
        cmp r7, r3
        jmp ne, crcbad
        or r4, r4, 0x80
crcbad: ld r3, [@0]                  ; PID
        cmp r3, 0x69
        jmp eq, rin                  ; IN token
        jbit r4.7, 0, report         ; anything else needs a good data packet
        cmp r3, 0xC3
        jmp eq, rack                 ; DATA0
        cmp r3, 0x4B
        jmp eq, rack                 ; DATA1
        jmp report
rack:   set r6, 0xD2                 ; ACK
        set r3, 0
        set r5, 0
        jmp tx
rin:    mov r7, flags
        jbit r7.4, 1, rdata
        set r6, 0x5A                 ; NAK: nothing prepared
        or r4, r4, 0x40              ; and the IN token is not reported
        set r3, 0
        set r5, 0
        jmp tx
rdata:  pull                         ; header of the prepared packet
        mov r7, osr
        and r3, r7, 15               ; bytes from the PID onwards
        set r5, 0
        jbit r7.7, 0, rdnc
        set r5, 2                    ; two CRC bytes after the data
rdnc:   irq clear 4

; ------------------------------------------------------------- send
tx:     set r7, 2                    ; phase: SYNC
        set r0, 0
        set r1, 0x80
        mov osr, r1                  ; SYNC, sent lowest bit first
        out null, 1                  ; its first bit (0) is the move to K at zK
        set r2, 6
        nop [15]                     ; turnaround: start about 2.5 bit times
        nop [15]                     ; after the end of the received packet
        nop [15]
        nop [15]
        nop [15] side 2              ; levels J, still released
        set dir DP, 1
        set dir DM, 1                ; driving J
        jmp zK

; One bit every 40 ticks. The instruction at t0 of each bit puts its level
; on the lines by side-set; "work" fetches the next bit into T and returns
; at t36; t36 and t37 end the packet after its last bit, t38 and t39 choose
; the next bit's entry: zJ / zK for a 0 (the line changes), oJ / oK for a 1
; (it stays), sJ / sK for a stuffed bit.
zK:     set r1, 5 side 1             ; t0: a 0, line K
        call work                    ; t1
        cmp r0, 2                    ; t36
        jmp eq, end                  ; t37: that was the last bit
        jmp t, oKe                   ; t38
        jmp zJ                       ; t39
zJ:     set r1, 5 side 2             ; t0: a 0, line J
        call work
        cmp r0, 2
        jmp eq, end
        jmp t, oJe
        jmp zK
oKe:    nop                          ; t39
oK:     jmp r1--, oKn side 1         ; t0: a 1, line stays K
        call work                    ; t1: the sixth 1: a stuffed 0 follows
        nop [2]                      ; t36 .. t38
        jmp sJ                       ; t39
oKn:    call work
        cmp r0, 2
        jmp eq, end
        jmp t, oKe
        jmp zJ
oJe:    nop
oJ:     jmp r1--, oJn side 2
        call work
        nop [2]
        jmp sK
oJn:    call work
        cmp r0, 2
        jmp eq, end
        jmp t, oJe
        jmp zK
sJ:     set r1, 5 side 2 [15]        ; t0 .. t15: stuffed bit, line J
        nop [15]                     ; t16 .. t31
        nop [3]                      ; t32 .. t35
        cmp r0, 2                    ; t36
        jmp eq, end                  ; t37
        jmp t, oJe                   ; t38
        jmp zK                       ; t39
sK:     set r1, 5 side 1 [15]
        nop [15]
        nop [3]
        cmp r0, 2
        jmp eq, end
        jmp t, oKe
        jmp zJ
end:    nop                          ; t38
        jmp eopt                     ; t39
eopt:   nop side 0 [15]              ; t0: SE0 for two bit times
        nop [15]
        nop [15]
        nop [15]
        nop [15]                     ; .. t79
        nop side 2 [15]              ; t80: J for one bit time
        nop [15]
        nop [7]                      ; .. t119
        set dir DP, 0                ; t120: release the lines
        set dir DM, 0

; ------------------------------------------------------------- report
report: jbit r4.6, 1, idle           ; an IN token answered with NAK
        and r7, r4, 31               ; bytes received
        cmp r7, 17
        jmp lt, rcnt
        set r7, 16                   ; only 16 fit in the data memory
rcnt:   mov isr, r4
        push                         ; header
        set r2, 0
rloop:  jmp !r7, idle
        ld r3, [r2]
        mov isr, r3
        push
        add r2, r2, 1
        sub r7, r7, 1
        jmp rloop

; Fetch the next bit into T (and through the checksum unit). At the end of a
; byte, load the next one: PID after SYNC, then FIFO bytes, then the two CRC
; bytes; when there is nothing left, set r0 = 1. The next call, which finds
; r0 = 1, fetches nothing and sets r0 = 2: the bit now on the line is the
; last. Starts at t2 and returns at t35 on every path.
work:   jmp r0, wend                 ; t2
        out t, 1, feed               ; t3
        jmp r2--, wpad               ; t4: more bits in this byte
        set r2, 7                    ; t5
        jmp !r7, bdat0               ; t6: phase 0
        sub r7, r7, 1                ; t7
        jmp !r7, bpid                ; t8: the PID has just been fetched
        jmp !r3, bhs                 ; t9: SYNC done; PID from r6 or the FIFO
        pull                         ; t10
        sub r3, r3, 1                ; t11
        nop [15]                     ; t12 .. t27
        nop [6]                      ; t28 .. t34
        ret                          ; t35
bhs:    mov osr, r6                  ; t10: handshake PID
        nop [15]                     ; t11 .. t26
        nop [7]                      ; t27 .. t34
        ret
bdat0:  nop [2]                      ; t7 .. t9
        jmp bdata                    ; t10
bpid:   mov crc_lo, null, inv        ; t9: CRC16 starts after the PID
        mov crc_hi, null             ; t10
bdata:  jmp !r3, bnof                ; t11: no FIFO bytes left
        pull                         ; t12
        sub r3, r3, 1                ; t13
        nop [15]                     ; t14 .. t29
        nop [4]                      ; t30 .. t34
        ret
bnof:   jmp r5--, bcrc               ; t12: CRC bytes left
        set r0, 1                    ; t13: nothing left
        nop [15]                     ; t14 .. t29
        nop [4]                      ; t30 .. t34
        ret
bcrc:   jmp !r5, bcrc2               ; t13
        mov r6, crc_lo, inv          ; t14: first CRC byte (low)
        mov osr, r6                  ; t15
        nop [15]                     ; t16 .. t31
        nop [2]                      ; t32 .. t34
        ret
bcrc2:  shr r6, r6, 8                ; t14: second CRC byte (high)
        mov osr, r6                  ; t15
        nop [15]
        nop [2]
        ret
wpad:   nop [15]                     ; t5 .. t20
        nop [13]                     ; t21 .. t34
        ret
wend:   set r0, 2                    ; t3
        nop [15]                     ; t4 .. t19
        nop [14]                     ; t20 .. t34
        ret
