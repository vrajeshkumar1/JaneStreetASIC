# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: Apache-2.0
"""Models of the other end of the wire, used by the engine tests
(test/engine) and the whole-chip tests (test/test.py).

Every model works on a Wires object (host.py), which gives it:
    set_in(n, level)   drive input pin n
    pull(n, low)       hold bidirectional line n low, or release it
    io(n)              level of bidirectional line n
    out(n)             level of output pin n
"""

from cocotb.triggers import ClockCycles, RisingEdge

# ------------------------------------------------------------------- UART


async def uart_send(w, pin, byte, bit_clocks, stop=1):
    """Send one 8N1 frame into input pin `pin`."""
    w.set_in(pin, 0)
    await ClockCycles(w.dut.clk, bit_clocks)
    for i in range(8):
        w.set_in(pin, (byte >> i) & 1)
        await ClockCycles(w.dut.clk, bit_clocks)
    w.set_in(pin, stop)
    await ClockCycles(w.dut.clk, bit_clocks)
    w.set_in(pin, 1)


async def uart_receive(w, pin, count, bit_clocks, got):
    """Decode `count` 8N1 frames from output pin `pin` into the list `got`."""
    clk = w.dut.clk
    while w.out(pin) == 0:                    # wait for the line to go idle
        await RisingEdge(clk)
    for _ in range(count):
        while w.out(pin) == 1:
            await RisingEdge(clk)
        await ClockCycles(clk, bit_clocks + bit_clocks // 2)
        byte = 0
        for i in range(8):
            byte |= w.out(pin) << i
            await ClockCycles(clk, bit_clocks)
        assert w.out(pin) == 1, "stop bit missing"
        got.append(byte)


# -------------------------------------------------------------------- SPI


async def spi_target(w, reply, seen, sck=3, mosi=1, miso=2):
    """Mode 0 target on bidirectional lines: samples MOSI on the rising clock
    edge, changes MISO on the falling edge. Answers with the bytes in `reply`
    and appends what it received to `seen`."""
    clk = w.dut.clk
    for out_byte in reply:
        in_byte = 0
        for i in range(8):
            w.pull(miso, not ((out_byte >> (7 - i)) & 1))
            await RisingEdge(clk)
            while w.io(sck) == 0:
                await RisingEdge(clk)
            in_byte = (in_byte << 1) | w.io(mosi)
            while w.io(sck) == 1:
                await RisingEdge(clk)
        seen.append(in_byte)


# -------------------------------------------------------------------- I2C

SCL, SDA = 6, 7


class I2CTargetModel:
    """A register-map device on the bus, for testing the controller program."""

    def __init__(self, wires, address):
        self.w = wires
        self.clk = wires.dut.clk
        self.address = address
        self.mem = {}
        self.pointer = 0
        self.log = []
        self.stretch_clocks = 0

    async def _edge(self):
        """Wait for the next change on either line. Returns 'start', 'stop', 'rise' or 'fall'."""
        scl, sda = self.w.io(SCL), self.w.io(SDA)
        while True:
            await RisingEdge(self.clk)
            nscl, nsda = self.w.io(SCL), self.w.io(SDA)
            if scl and nscl and sda and not nsda:
                return "start"
            if scl and nscl and not sda and nsda:
                return "stop"
            if not scl and nscl:
                return "rise"
            if scl and not nscl:
                return "fall"
            scl, sda = nscl, nsda

    async def _byte(self):
        """Receive 8 bits. Returns the byte, or 'start' / 'stop'."""
        value = 0
        for _ in range(8):
            while True:
                e = await self._edge()
                if e in ("start", "stop"):
                    return e
                if e == "rise":
                    value = (value << 1) | self.w.io(SDA)
                    break
            while True:
                e = await self._edge()
                if e in ("start", "stop"):
                    return e
                if e == "fall":
                    break
        return value

    async def _ack(self, ack=True):
        self.w.pull(SDA, ack)
        if self.stretch_clocks:
            self.w.pull(SCL, True)
            await ClockCycles(self.clk, self.stretch_clocks)
            self.w.pull(SCL, False)
        while await self._edge() != "rise":
            pass
        while await self._edge() != "fall":
            pass
        self.w.pull(SDA, False)

    async def _send(self, byte):
        for i in range(8):
            self.w.pull(SDA, not ((byte >> (7 - i)) & 1))
            while await self._edge() != "rise":
                pass
            while await self._edge() != "fall":
                pass
        self.w.pull(SDA, False)
        while await self._edge() != "rise":
            pass
        nack = self.w.io(SDA)
        while True:
            e = await self._edge()
            if e == "fall":
                break
            if e in ("start", "stop"):
                return e
        return "nack" if nack else "ack"

    async def run(self):
        state = "idle"
        while True:
            if state == "idle":
                while await self._edge() != "start":
                    pass
                state = "address"
            if state == "address":
                self.log.append("start")
                while await self._edge() != "fall":
                    pass
                first = await self._byte()
                if first in ("start", "stop"):
                    state = "address" if first == "start" else "idle"
                    continue
                if first >> 1 != self.address:
                    state = "idle"
                    continue
                await self._ack()
                if first & 1:
                    while True:
                        r = await self._send(self.mem.get(self.pointer, 0xEE))
                        self.pointer = (self.pointer + 1) & 0xFF
                        if r != "ack":
                            break
                    state = "address" if r == "start" else "idle"
                    if r == "stop":
                        self.log.append("stop")
                    continue
                got_pointer = False
                while True:
                    value = await self._byte()
                    if value == "start":
                        state = "address"
                        break
                    if value == "stop":
                        self.log.append("stop")
                        state = "idle"
                        break
                    if not got_pointer:
                        self.pointer, got_pointer = value, True
                    else:
                        self.mem[self.pointer] = value
                        self.pointer = (self.pointer + 1) & 0xFF
                    await self._ack()


class I2CControllerModel:
    """Bit-banged controller on the bus, for testing the target program."""

    def __init__(self, wires, half_clocks):
        self.w = wires
        self.clk = wires.dut.clk
        self.h = half_clocks

    async def _t(self, n=1):
        await ClockCycles(self.clk, self.h * n)

    async def start(self):
        self.w.pull(SDA, False)
        await self._t()
        self.w.pull(SCL, False)
        await self._t()
        self.w.pull(SDA, True)
        await self._t()
        self.w.pull(SCL, True)
        await self._t()

    async def stop(self):
        self.w.pull(SDA, True)
        await self._t()
        self.w.pull(SCL, False)
        await self._t()
        self.w.pull(SDA, False)
        await self._t()

    async def _clock(self):
        """One clock pulse; returns SDA sampled while the clock is high."""
        await self._t()
        self.w.pull(SCL, False)
        await self._t()
        bit = self.w.io(SDA)
        self.w.pull(SCL, True)
        return bit

    async def write(self, byte):
        for i in range(8):
            self.w.pull(SDA, not ((byte >> (7 - i)) & 1))
            await self._clock()
        self.w.pull(SDA, False)
        nack = await self._clock()
        return not nack

    async def read(self, ack):
        value = 0
        self.w.pull(SDA, False)
        for _ in range(8):
            value = (value << 1) | await self._clock()
        self.w.pull(SDA, ack)
        await self._clock()
        self.w.pull(SDA, False)
        return value


# ---------------------------------------------------------- USB low speed

def usb_crc5(value11):
    """CRC5 of a token's 11 address and endpoint bits."""
    crc = 0x1F
    for i in range(11):
        fb = (crc & 1) ^ ((value11 >> i) & 1)
        crc >>= 1
        if fb:
            crc ^= 0x14
    return crc ^ 0x1F


def usb_crc16(data, crc=0xFFFF):
    """Running CRC16 of data packets (not inverted)."""
    for byte in data:
        for i in range(8):
            fb = (crc & 1) ^ ((byte >> i) & 1)
            crc >>= 1
            if fb:
                crc ^= 0xA001
    return crc


def usb_token(pid, addr, endp):
    v = addr | (endp << 7)
    v |= usb_crc5(v) << 11
    return [pid, v & 0xFF, v >> 8]


def usb_data(pid, data):
    c = usb_crc16(data) ^ 0xFFFF
    return [pid] + list(data) + [c & 0xFF, c >> 8]


class USBLowSpeedHostModel:
    """The host end of a low-speed USB cable: drives D+ / D- with NRZI coding
    and bit stuffing, and decodes what the device sends back. Idle is J
    (D+ low, D- high), as the pull-up on D- and the host's pull-down on D+
    hold it."""

    J, K, SE0 = (0, 1), (1, 0), (0, 0)

    def __init__(self, wires, dp=4, dm=5, bit_clocks=40.0, skew=0):
        self.w = wires
        self.clk = wires.dut.clk
        self.dp, self.dm = dp, dm
        self.bit_clocks = bit_clocks      # 40 at 60 MHz; other values model a fast or slow host
        self.skew = skew                  # D- changes this many clocks after D+
        self._put(self.J)
        self.eop_end = None               # clock count when the host's last EOP ended
        self.clocks = 0
        self._counter_started = False

    def _put(self, state):
        self.w.pull(self.dp, not state[0])
        self.w.pull(self.dm, not state[1])

    def line(self):
        return (self.w.io(self.dp), self.w.io(self.dm))

    async def _count(self):
        while True:
            await RisingEdge(self.clk)
            self.clocks += 1

    def start_counter(self):
        if not self._counter_started:
            import cocotb
            cocotb.start_soon(self._count())
            self._counter_started = True

    @staticmethod
    def _bits(packet):
        """SYNC and packet bytes, lowest bit first, with bit stuffing."""
        raw = [(0x80 >> i) & 1 for i in range(8)]
        for byte in packet:
            raw += [(byte >> i) & 1 for i in range(8)]
        out, ones = [], 0
        for b in raw:
            out.append(b)
            ones = ones + 1 if b else 0
            if ones == 6:
                out.append(0)
                ones = 0
        return out

    async def send(self, packet):
        """Send one packet (PID onwards, with its CRC) followed by an EOP."""
        self.start_counter()
        states, level = [], self.J
        for b in self._bits(packet):
            if b == 0:
                level = self.K if level == self.J else self.J
            states.append(level)
        states += [self.SE0, self.SE0, self.J]
        t = 0.0
        done = 0
        for st in states:
            if self.skew and st != self.SE0:
                self.w.pull(self.dp, not st[0])
                await ClockCycles(self.clk, self.skew)
                self.w.pull(self.dm, not st[1])
                done += self.skew
            else:
                self._put(st)
            t += self.bit_clocks
            wait = int(round(t)) - done
            await ClockCycles(self.clk, wait)
            done += wait
        self.eop_end = self.clocks - int(round(self.bit_clocks))   # SE0 to J
        self._put(self.J)

    async def receive(self, timeout=2000):
        """Wait for a packet from the device. Returns (bytes from the PID
        onwards, clocks from the end of the host's EOP to the start of SYNC).
        Checks that every transition falls on a 40-clock grid from the start
        of SYNC, and that the EOP is 80 clocks of SE0 then J."""
        self.start_counter()
        for _ in range(timeout):
            await RisingEdge(self.clk)
            if self.line() == self.K:
                break
        else:
            return None, None
        start = self.clocks
        gap = start - self.eop_end if self.eop_end is not None else None
        samples = [self.K]
        while True:
            await RisingEdge(self.clk)
            samples.append(self.line())
            if len(samples) > 80 and all(s == self.SE0 for s in samples[-80:]):
                break
            assert len(samples) < 40 * 200, "no end of packet"
        for _ in range(45):
            await RisingEdge(self.clk)
            samples.append(self.line())
        # Every change of state is on the 40-clock grid.
        for i in range(1, len(samples)):
            if samples[i] != samples[i - 1]:
                assert i % 40 == 0, f"transition {i} clocks after the start of SYNC"
        se0 = samples.index(self.SE0)
        assert samples[se0:se0 + 80] == [self.SE0] * 80 and samples[se0 + 80] == self.J, \
            "end of packet is not two bit times of SE0 then J"
        levels = [samples[20 + 40 * k] for k in range(se0 // 40)]
        bits, prev, ones, skip = [], self.J, 0, False
        for lv in levels:
            b = 1 if lv == prev else 0
            prev = lv
            if skip:
                assert b == 0, "missing stuffed bit"
                skip = False
                ones = 0
                continue
            bits.append(b)
            ones = ones + 1 if b else 0
            if ones == 6:
                skip = True
        assert bits[:8] == [0, 0, 0, 0, 0, 0, 0, 1], "no SYNC"
        bits = bits[8:]
        assert len(bits) % 8 == 0, f"{len(bits)} bits is not whole bytes"
        data = [sum(bits[8 * n + i] << i for i in range(8)) for n in range(len(bits) // 8)]
        return data, gap


# ------------------------------------------------------------- 10BASE-T

async def capture_10base_t(w, plus=6, minus=7, timeout=400000):
    """Record TD+ / TD- (output pins) from the start of a frame until the line
    has been idle (both low) for 30 clocks. Returns a list of (TD+, TD-)."""
    clk = w.dut.clk
    for _ in range(timeout):
        await RisingEdge(clk)
        if w.out(plus) or w.out(minus):
            break
    else:
        return None
    samples = [(w.out(plus), w.out(minus))]
    while not (len(samples) > 30 and all(s == (0, 0) for s in samples[-30:])):
        await RisingEdge(clk)
        samples.append((w.out(plus), w.out(minus)))
    return samples


def decode_10base_t(samples, half=3):
    """Check and decode a captured frame. Returns (frame bytes after the
    start-of-frame delimiter, TP_IDL length in clocks). Checks that TD- is the
    complement of TD+ until the end, that every change is on a 3-clock grid,
    and that every bit has a change in its middle (Manchester code: the
    second half carries the bit)."""
    end = next(i for i, s in enumerate(samples) if s == (0, 0))
    assert all(p != n for p, n in samples[:end]), "TD+ and TD- not complementary"
    for i in range(1, end):
        if samples[i] != samples[i - 1]:
            assert i % half == 0, f"change {i} clocks after the start is off the grid"
    bits = []
    i = 0
    while i + 2 * half <= end:
        first = samples[i + half // 2][0]
        second = samples[i + half + half // 2][0]
        if first == second:
            break                                   # no mid-bit change: end of frame
        bits.append(second)
        i += 2 * half
    # TP_IDL: TD+ high from the last bit's end (or its rising middle) until idle.
    last = i
    while last > 0 and samples[last - 1][0] == 1:
        last -= 1
    tp_idl = end - max(last, i - half)
    data = [sum(bits[8 * n + k] << k for k in range(8)) for n in range(len(bits) // 8)]
    assert len(bits) % 8 == 0, f"{len(bits)} bits"
    assert data[:8] == [0x55] * 7 + [0xD5], f"preamble / delimiter {data[:8]}"
    return data[8:], tp_idl


async def link_pulses(w, count, plus=6, minus=7, timeout=400000):
    """Times (in clocks) and widths of the next `count` link pulses."""
    clk = w.dut.clk
    starts, widths, t = [], [], 0
    while len(starts) < count:
        await RisingEdge(clk)
        t += 1
        assert t < timeout, "no link pulse"
        if w.out(plus):
            starts.append(t)
            width = 0
            while w.out(plus):
                assert not w.out(minus)
                await RisingEdge(clk)
                t += 1
                width += 1
            widths.append(width)
    return starts, widths
