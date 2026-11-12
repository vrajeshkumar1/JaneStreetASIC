# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
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
