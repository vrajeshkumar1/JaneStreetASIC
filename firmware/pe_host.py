# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
"""Host driver for the protocol emulator chip (docs/spec.md, part 2).

Runs under MicroPython on the RP2350 of the Tiny Tapeout demo board, under
MicroPython on any other board wired to the PYNQ-Z2 build (fpga/), and under
CPython for checking. The chip is reached through a "link" that moves bytes
over the SPI host interface; three are provided:

    TTBoardLink()                 demo board: host select, clock and data on
                                  ui_in[0..2], data back on uo_out[0]
    PinLink(sel, sck, mosi, miso) any MicroPython board, bit by bit on four
                                  machine.Pin objects
    SPILink(spi, sel)             any MicroPython board, a machine.SPI in
                                  mode 0 (at most 7.5 MHz with a 60 MHz chip
                                  clock) plus a host select pin

    chip = Chip(TTBoardLink())
    chip.load(0, PROGRAMS["uart_tx"])

Programs are assembled on a PC with tools/pasm.py; firmware/make_programs.py
writes all of programs/ into firmware/programs.py for copying to the board.
"""

# ---- global registers
ID, VERSION, ENABLE, RESTART = 0x00, 0x01, 0x02, 0x03
FLAGS, FLAGS_SET, FLAGS_CLR = 0x04, 0x05, 0x06
ATTN_MASK, CTRL, STATUS = 0x07, 0x08, 0x09
OWNER_OUT, OWNER_IO = 0x10, 0x12
DRIVE_OUT, DRIVE_IO, OPEN_DRAIN = 0x14, 0x15, 0x16

# ---- engine registers (offsets from the engine's base)
E_CFG, E_PULL_THRESH, E_PUSH_THRESH, E_CLKDIV = 0x00, 0x01, 0x02, 0x03
E_SIDE0, E_SIDE1, E_PC, E_STATUS = 0x05, 0x06, 0x07, 0x09
E_TX_LEVEL, E_RX_LEVEL, E_FIFO, E_DEBUG = 0x0A, 0x0B, 0x0C, 0x0D
E_CRC_POLY, E_CRC_WIDTH, E_SIZES, E_CRC = 0x0E, 0x12, 0x13, 0x14
E_DM_SIZE, E_FEATURES, E_R0 = 0x18, 0x19, 0x20

# ---- engine STATUS bits
ST_RUNNING, ST_STALLED, ST_HALTED, ST_ILLEGAL = 0x01, 0x02, 0x04, 0x08
ST_TX_EMPTY, ST_TX_FULL, ST_RX_EMPTY, ST_RX_FULL = 0x10, 0x20, 0x40, 0x80

CHIP_ID = 0x4A


def ereg(e, offset):
    return 0x0100 + 0x40 * e + offset


def dmem(e, offset=0):
    return 0x0200 + 0x10 * e + offset


def prog(e, word=0):
    return 0x4000 + 0x800 * e + 4 * word


def pin(name):
    """Number of a writable pin ("out0".."out7", "io0".."io7"), as SIDE0 /
    SIDE1 use it."""
    kind, n = name[:-1], int(name[-1])
    return {"out": 0, "io": 8}[kind] + n


# --------------------------------------------------------------- links

class PinLink:
    """SPI mode 0, highest bit first, on four pins. The clock is as slow as
    the Python loop, which is always slow enough for the chip."""

    def __init__(self, sel, sck, mosi, miso):
        self.sel, self.sck, self.mosi, self.miso = sel, sck, mosi, miso
        self.sel.value(1)
        self.sck.value(0)

    def begin(self):
        self.sel.value(0)
        self.sck.value(0)

    def end(self):
        self.sel.value(1)

    def xfer(self, data):
        out = bytearray(len(data))
        for k, value in enumerate(data):
            got = 0
            for i in range(7, -1, -1):
                self.mosi.value((value >> i) & 1)
                got = (got << 1) | self.miso.value()
                self.sck.value(1)
                self.sck.value(0)
            out[k] = got
        return out


class SPILink:
    """A machine.SPI set to mode 0 (polarity 0, phase 0, highest bit first)
    and a host select pin."""

    def __init__(self, spi, sel):
        self.spi, self.sel = spi, sel
        self.sel.value(1)

    def begin(self):
        self.sel.value(0)

    def end(self):
        self.sel.value(1)

    def xfer(self, data):
        buf = bytearray(data)
        self.spi.write_readinto(bytes(data), buf)
        return buf


class TTBoardLink:
    """The Tiny Tapeout demo board: the RP2350 drives ui_in and reads uo_out
    through the ttboard SDK. ui_in[3..7] keep the levels given to
    set_inputs(), so the host can also drive protocol inputs. The SPI pins
    are moved only while host select is low and put back before it rises
    (docs/spec.md, section 2.1)."""

    def __init__(self, tt=None):
        if tt is None:
            from ttboard.demoboard import DemoBoard
            tt = DemoBoard.get()
        from ttboard.mode import RPMode
        tt.mode = RPMode.ASIC_RP_CONTROL
        self.tt = tt
        try:
            import ttboard.util.platform as platform
            self._w = platform.write_ui_in_byte
            self._r = platform.read_uo_out_byte
        except (ImportError, AttributeError):
            self._w = lambda v: setattr(self.tt.ui_in, "value", v)
            self._r = lambda: int(self.tt.uo_out.value)
        self.ui = 0x01                       # host select high
        self._w(self.ui)

    def set_inputs(self, value):
        """Levels of ui_in[1..7] while the host is not talking to the chip."""
        self.ui = (value & 0xFE) | 0x01
        self._w(self.ui)

    def begin(self):
        self.ui &= ~0x01
        self._w(self.ui)
        self._rest = self.ui & 0x06
        self.ui &= ~0x06                     # clock low
        self._w(self.ui)

    def end(self):
        self.ui = (self.ui & ~0x06) | self._rest
        self._w(self.ui)
        self.ui |= 0x01
        self._w(self.ui)

    def xfer(self, data):
        out = bytearray(len(data))
        w, r = self._w, self._r
        base = self.ui & ~0x06
        for k, value in enumerate(data):
            got = 0
            for i in range(7, -1, -1):
                base = (self.ui & ~0x06) | (((value >> i) & 1) << 2)
                w(base)
                got = (got << 1) | (r() & 1)
                w(base | 0x02)
            w(base)
            out[k] = got
        self.ui = base
        return out


# ---------------------------------------------------------------- chip

class Chip:
    """The host's view of the chip. It keeps a copy of the engine enables,
    pin owners, open-drain pins and pin drivers it has written, so that the
    protocol helpers below can each change their own engine and pins without
    disturbing the others."""

    def __init__(self, link):
        self.link = link
        self.running = 0
        self.owner_out, self.owner_io = {}, {}
        self.open_drain = set()
        self.driven_out, self.driven_io = set(), set()

    # ---- transfers (section 2.2)
    def write(self, addr, data):
        if isinstance(data, int):
            data = [data]
        self.link.begin()
        self.link.xfer([0x80 | (addr >> 8), addr & 0xFF] + list(data))
        self.link.end()

    def read(self, addr, n=1):
        self.link.begin()
        got = self.link.xfer([addr >> 8, addr & 0xFF, 0] + [0] * n)
        self.link.end()
        return list(got[3:])

    def read1(self, addr):
        return self.read(addr, 1)[0]

    # ---- whole chip
    def check(self):
        """True if the chip answers with its ID."""
        return self.read1(ID) == CHIP_ID

    def enable(self, mask):
        """Run exactly the engines in mask."""
        self.running = mask & 0x0F
        self.write(ENABLE, self.running)

    def start(self, e):
        self.enable(self.running | (1 << e))

    def stop(self, e):
        self.enable(self.running & ~(1 << e))

    def restart(self, mask):
        self.write(RESTART, mask)

    def flags(self):
        return self.read1(FLAGS)

    def set_flags(self, mask):
        self.write(FLAGS_SET, mask)

    def clear_flags(self, mask):
        self.write(FLAGS_CLR, mask)

    def pins(self, out=None, io=None, open_drain=()):
        """Give pins to engines. out / io: {pin number: engine}. Pins not
        named keep their owners. open_drain: bidirectional pins to add to
        the open-drain set."""
        self.owner_out.update(out or {})
        self.owner_io.update(io or {})
        self.open_drain.update(open_drain)
        owner_out = sum(e << (2 * n) for n, e in self.owner_out.items())
        owner_io = sum(e << (2 * n) for n, e in self.owner_io.items())
        self.write(OWNER_OUT, [owner_out & 0xFF, owner_out >> 8,
                               owner_io & 0xFF, owner_io >> 8])
        self.write(OPEN_DRAIN, sum(1 << n for n in self.open_drain))

    def drive(self, out=(), io=()):
        """Switch these pin drivers on, keeping those already on. Done after
        the owning engine has started, so that its program has set the pin
        levels first (section 2.6)."""
        self.driven_out.update(out)
        self.driven_io.update(io)
        self.write(DRIVE_OUT, [sum(1 << n for n in self.driven_out),
                               sum(1 << n for n in self.driven_io)])

    def release(self, out=(), io=()):
        """Switch these pin drivers off (outputs held low, bidirectional pins
        become inputs)."""
        self.driven_out.difference_update(out)
        self.driven_io.difference_update(io)
        self.drive()

    # ---- one engine
    def load(self, e, program, entry=None):
        """program: {"words": [...], "labels": {...}} from firmware/programs.py,
        or a plain list of words. The engine must be stopped."""
        words = program["words"] if isinstance(program, dict) else program
        data = []
        for w in words:
            data += [w & 0xFF, (w >> 8) & 0xFF, (w >> 16) & 0xFF, (w >> 24) & 0xFF]
        self.write(prog(e), data)
        self.set_pc(e, program["labels"][entry] if entry else 0)

    def write_memory(self, e, byte_addr, data):
        """Bytes into the spare part of an engine's memory block, which
        programs reach with ldm / stm. The engine must be stopped. byte_addr
        must be a multiple of 4; the data is padded to whole words."""
        data = list(data) + [0] * (-len(data) % 4)
        self.write(prog(e) + byte_addr, data)

    def configure(self, e, clkdiv=0, out_dir=0, in_dir=0, autopull=0, autopush=0,
                  crc_dir=0, pull_thresh=8, push_thresh=8,
                  side0=None, side1=None, side0_dir=False, side1_dir=False):
        """Engine settings (section 2.5). side0 / side1 are pin names such
        as "out4" or "io6"."""
        def side(name, direction):
            if name is None:
                return 0
            return 0x10 | pin(name) | (0x20 if direction else 0)
        cfg = out_dir | (in_dir << 1) | (autopull << 2) | (autopush << 3) | (crc_dir << 4)
        self.write(ereg(e, E_CFG), [cfg, pull_thresh, push_thresh, clkdiv & 0xFF, clkdiv >> 8,
                                    side(side0, side0_dir), side(side1, side1_dir)])

    def set_crc(self, e, poly, width):
        """Checksum unit (engines 2 and 3)."""
        self.write(ereg(e, E_CRC_POLY), [poly & 0xFF, (poly >> 8) & 0xFF,
                                         (poly >> 16) & 0xFF, (poly >> 24) & 0xFF, width])

    def set_pc(self, e, address):
        self.write(ereg(e, E_PC), [address & 0xFF, address >> 8])

    def pc(self, e):
        lo, hi = self.read(ereg(e, E_PC), 2)
        return lo | (hi << 8)

    def set_reg(self, e, n, value):
        self.write(ereg(e, E_R0 + 2 * n), [value & 0xFF, (value >> 8) & 0xFF])

    def write_dm(self, e, offset, data):
        self.write(dmem(e, offset), data)

    def sizes(self, e):
        """(program words, FIFO bytes, data memory bytes, has checksum unit,
        has 16-place shifter) of engine e."""
        s = self.read1(ereg(e, E_SIZES))
        d = self.read1(ereg(e, E_DM_SIZE))
        f = self.read1(ereg(e, E_FEATURES))
        return 1 << (s & 15), 1 << (s >> 4), 1 << (d & 15), bool(f & 1), bool(f & 2)

    def status(self, e):
        return self.read1(ereg(e, E_STATUS))

    def rx_level(self, e):
        return self.read1(ereg(e, E_RX_LEVEL))

    def tx_level(self, e):
        return self.read1(ereg(e, E_TX_LEVEL))

    def push(self, e, data):
        self.write(ereg(e, E_FIFO), data)

    def pop(self, e, n=1):
        return self.read(ereg(e, E_FIFO), n)

    def collect(self, e, n, tries=1000):
        """n bytes from the RX FIFO, taken as they arrive. n may be larger
        than the FIFO."""
        out = []
        for _ in range(tries):
            level = self.rx_level(e)
            if level:
                out += self.pop(e, min(level, n - len(out)))
            if len(out) >= n:
                return out
        raise OSError("engine %d: %d of %d bytes arrived" % (e, len(out), n))


# ------------------------------------------------- protocol helpers

def usb_crc16(data, crc=0xFFFF):
    for byte in data:
        for i in range(8):
            fb = (crc & 1) ^ ((byte >> i) & 1)
            crc >>= 1
            if fb:
                crc ^= 0xA001
    return crc


class USBDevice:
    """Host side of programs/usb_ls_device.s on engine 3, D+ on io4 and D-
    on io5 (programs/README.md). The engine answers within the bus
    turnaround time by itself; the host reads each received packet and
    prepares the answer to the next IN token."""

    E = 3

    def __init__(self, chip, programs):
        self.chip = c = chip
        c.stop(self.E)
        c.restart(1 << self.E)
        c.load(self.E, programs["usb_ls_device"])
        c.configure(self.E, side0="io4", side1="io5")
        c.set_crc(self.E, 0xA001, 16)
        c.pins(io={4: self.E, 5: self.E})
        c.start(self.E)
        c.drive(io=[4, 5])

    def packet(self):
        """The next received packet as (PID and data bytes, CRC16 good),
        or None. For a data packet the last two bytes are its CRC16."""
        c = self.chip
        if not c.rx_level(self.E):
            return None
        hdr = c.collect(self.E, 1)[0]
        data = c.collect(self.E, min(hdr & 0x1F, 16))
        return data, bool(hdr & 0x80)

    def prepare(self, pid, data=None):
        """Packet for the next IN token: a data PID with up to 8 data bytes
        (the engine adds the CRC16), or a handshake PID alone."""
        if data is None:
            self.chip.push(self.E, [1, pid])
        else:
            self.chip.push(self.E, [0x80 | (len(data) + 1), pid] + list(data))
        self.chip.set_flags(1 << 4)


class Ethernet:
    """Host side of programs/eth_tx.s on engine 2, TD+ on out6 and TD- on
    out7 (programs/README.md)."""

    E = 2
    FRAME = 528          # .define FRAME in eth_tx.s

    def __init__(self, chip, programs):
        self.chip = c = chip
        c.stop(self.E)
        c.restart(1 << self.E)
        c.load(self.E, programs["eth_tx"])
        c.configure(self.E, side0="out6", side1="out7")
        c.set_crc(self.E, 0xEDB88320, 32)
        c.pins(out={6: self.E, 7: self.E})
        c.start(self.E)
        c.drive(out=[6, 7])
        self.send_label = programs["eth_tx"]["labels"]["send"]

    def busy(self):
        """True while a frame is waiting or going out: flag 5 still set, or
        the engine past its idle loop."""
        c = self.chip
        return bool(c.flags() & (1 << 5)) or c.pc(self.E) >= self.send_label

    def send(self, frame, tries=10000):
        """frame: destination address to the end of the data, 60 to 1,514
        bytes (shorter frames are padded to 60). Waits for the previous frame
        to go out, stops the engine while the frame is written into its
        memory block, then has it sent with preamble and FCS."""
        c = self.chip
        frame = list(frame) + [0] * max(0, 60 - len(frame))
        for _ in range(tries):
            if not self.busy():
                break
        else:
            raise OSError("Ethernet engine still busy")
        c.stop(self.E)
        c.write_memory(self.E, self.FRAME, frame)
        c.start(self.E)
        c.push(self.E, [len(frame) & 0xFF, len(frame) >> 8])
        c.set_flags(1 << 5)
