#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
# SPDX-License-Identifier: MIT
"""Assembler for the protocol engine (docs/spec.md, part 1).

Use as a module:

    from pasm import assemble
    prog = assemble(open("uart_tx.s").read())
    prog.words     # list of 32-bit instruction words
    prog.labels    # {"send": 0, "bit": 2, ...}

or from the command line:

    python tools/pasm.py programs/uart_tx.s

Source notation, one instruction per line:

    label:  [ift|ifn] mnemonic operands   [side V] [[N]]   ; comment

Directives:

    .define NAME value      NAME can then be used wherever value could
    .org ADDRESS            continue at this word address; the gap is filled with halt
"""

import re
import sys
from dataclasses import dataclass, field

OP = dict(jmp=0, jbit=1, wait=2, inp=3, out=4, pp=5, mov=6, irq=7, set=8,
          alur=9, alui=10, ld=11, st=12, call=13, pin=14, halt=15)

JMP_TESTS = {
    "eq": 4, "ne": 5, "lt": 6, "ge": 7, "t": 8, "!t": 9,
    "!osre": 10, "osre": 11, "txempty": 12, "!txempty": 13,
    "rxfull": 14, "!rxfull": 15,
}

ALU_FN = dict(add=0, sub=1, shl=5, shr=6, cmp=7)
ALU_FN.update({"and": 2, "or": 3, "xor": 4})

MOV_SRC = dict(isr=8, osr=9, pins_in=10, pins_io=11, wtime=12, crc_lo=13,
               crc_hi=14, null=15, lr=16, pc=17, status=18, flags=19)
MOV_DST = dict(isr=8, osr=9, pins_out=10, pins_io=11, dir_io=12, crc_lo=13,
               crc_hi=14, null=15, lr=16, pc=17)
MOV_OP = dict(inv=1, rev=2, par=3)


class AsmError(Exception):
    pass


@dataclass
class Program:
    words: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)
    lines: list = field(default_factory=list)   # source text of each instruction

    def hex(self):
        return "\n".join(f"{w:08x}" for w in self.words)


def _reg(tok):
    m = re.fullmatch(r"r([0-7])", tok)
    if not m:
        raise AsmError(f"expected a register r0..r7, got '{tok}'")
    return int(m.group(1))


def _is_reg(tok):
    return re.fullmatch(r"r[0-7]", tok) is not None


class _Asm:
    def __init__(self, text):
        self.defs = {}
        self.labels = {}
        self.items = []     # (line number, source, cond, mnemonic, operands, side, delay)
        self._parse(text)

    # ------------------------------------------------------------ parsing
    def _parse(self, text):
        for num, raw in enumerate(text.splitlines(), 1):
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            if line.startswith(".define"):
                parts = line.split()
                if len(parts) != 3:
                    raise AsmError(f"line {num}: .define NAME value")
                self.defs[parts[1].lower()] = parts[2].lower()
                continue
            if line.startswith(".org"):
                parts = line.split()
                try:
                    where = int(parts[1], 0)
                except (IndexError, ValueError):
                    raise AsmError(f"line {num}: .org ADDRESS")
                if where < len(self.items) or where > 511:
                    raise AsmError(f"line {num}: .org must move forward and stay below 512")
                while len(self.items) < where:
                    self.items.append((num, "(.org fill)", 0, "halt", [], None, 0))
                continue
            m = re.match(r"^([A-Za-z_]\w*):\s*(.*)$", line)
            if m:
                name = m.group(1).lower()
                if name in self.labels:
                    raise AsmError(f"line {num}: label '{name}' defined twice")
                self.labels[name] = len(self.items)
                line = m.group(2).strip()
                if not line:
                    continue
            delay = 0
            m = re.search(r"\[\s*(\d+)\s*\]\s*$", line)
            if m:
                delay = int(m.group(1))
                line = line[:m.start()].strip()
            side = None
            m = re.search(r"\bside\s+(\S+)\s*$", line)
            if m:
                side = int(m.group(1), 0)
                line = line[:m.start()].strip()
            cond = 0
            m = re.match(r"^(ift|ifn)\s+(.*)$", line, re.I)
            if m:
                cond = 1 if m.group(1).lower() == "ift" else 2
                line = m.group(2).strip()
            parts = line.split(None, 1)
            mnem = parts[0].lower()
            ops = [o.strip().lower() for o in parts[1].split(",")] if len(parts) > 1 else []
            if not 0 <= delay <= 15:
                raise AsmError(f"line {num}: delay must be 0..15")
            if side is not None and not 0 <= side <= 3:
                raise AsmError(f"line {num}: side value must be 0..3")
            self.items.append((num, raw.strip(), cond, mnem, ops, side, delay))

    # ----------------------------------------------------------- operands
    def _sub(self, tok):
        return self.defs.get(tok, tok)

    def _val(self, tok, bits):
        tok = self._sub(tok)
        if tok in self.labels:
            v = self.labels[tok]
        else:
            try:
                v = int(tok, 0)
            except ValueError:
                raise AsmError(f"'{tok}' is not a number, a .define or a label")
        if not 0 <= v < (1 << bits):
            raise AsmError(f"value {v} does not fit in {bits} bits")
        return v

    def _target(self, tok):
        tok = self._sub(tok)
        if tok not in self.labels:
            raise AsmError(f"unknown label '{tok}'")
        return self.labels[tok]

    def _pin(self, tok, write):
        tok = self._sub(tok)
        m = re.fullmatch(r"(in|out|io)([0-7])", tok)
        if not m:
            raise AsmError(f"'{tok}' is not a pin (in0..in7, out0..out7, io0..io7)")
        kind, n = m.group(1), int(m.group(2))
        if kind == "io":
            return 8 + n
        if kind == "in" and write:
            raise AsmError(f"'{tok}' is an input pin and cannot be written")
        if kind == "out" and not write:
            raise AsmError(f"'{tok}' is an output pin and cannot be read")
        return n

    @staticmethod
    def _split_kw(tok, kw):
        """'pin io3' -> 'io3' if tok starts with the keyword, else None."""
        parts = tok.split()
        if len(parts) == 2 and parts[0] == kw:
            return parts[1]
        return None

    def _mem(self, tok):
        """[rN], [rN+off], [@off] -> (use_base, base, offset)"""
        m = re.fullmatch(r"\[\s*(.*?)\s*\]", tok)
        if not m:
            raise AsmError(f"expected a memory operand like [r2], [r2+3] or [@5], got '{tok}'")
        inner = m.group(1).replace(" ", "")
        if inner.startswith("@"):
            return 0, 0, self._val(inner[1:], 4)
        if "+" in inner:
            base, off = inner.split("+", 1)
            return 1, _reg(base), self._val(off, 4)
        return 1, _reg(inner), 0

    # ----------------------------------------------------------- encoding
    def _jmp_test(self, tok):
        """-> (test code, register)"""
        tok = self._sub(tok)
        if tok in JMP_TESTS:
            return JMP_TESTS[tok], 0
        if tok.startswith("!") and _is_reg(tok[1:]):
            return 1, _reg(tok[1:])
        if tok.endswith("--") and _is_reg(tok[:-2]):
            return 2, _reg(tok[:-2])
        if _is_reg(tok):
            return 3, _reg(tok)
        raise AsmError(f"unknown jump test '{tok}'")

    def _bit_src(self, tok):
        """'pin io3' or 'r3.0' -> (source, reg, bit)"""
        p = self._split_kw(tok, "pin")
        if p is not None:
            return 0, 0, self._pin(p, write=False)
        m = re.fullmatch(r"(r[0-7])\.(\d+)", tok)
        if m:
            bit = int(m.group(2))
            if bit > 15:
                raise AsmError("bit number must be 0..15")
            return 1, _reg(m.group(1)), bit
        raise AsmError(f"expected 'pin NAME' or 'rN.bit', got '{tok}'")

    def _encode(self, mnem, ops):
        n = len(ops)

        if mnem in ("jmp", "tst"):
            mode = 1 if mnem == "tst" else 0
            if mode:
                if n != 1:
                    raise AsmError("tst TEST")
                code, reg = self._jmp_test(ops[0])
                tgt = 0
            elif n == 1:
                code, reg, tgt = 0, 0, self._target(ops[0])
            elif n == 2:
                code, reg = self._jmp_test(ops[0])
                tgt = self._target(ops[1])
            else:
                raise AsmError("jmp [TEST,] label")
            return OP["jmp"], (mode << 18) | (code << 14) | (reg << 10) | tgt

        if mnem in ("jbit", "tbit"):
            mode = 1 if mnem == "tbit" else 0
            if n != (2 if mode else 3):
                raise AsmError("jbit SOURCE, value, label   /   tbit SOURCE, value")
            src, reg, bit = self._bit_src(ops[0])
            val = self._val(ops[1], 1)
            tgt = 0 if mode else self._target(ops[2])
            return OP["jbit"], (mode << 18) | (src << 17) | (bit << 13) | (reg << 10) | (val << 9) | tgt

        if mnem == "wait":
            tmo_en, tmo_reg = 0, 0
            if ops and ops[-1].startswith("timeout"):
                tmo_en, tmo_reg = 1, _reg(ops[-1].split()[1])
                ops = ops[:-1]
                n -= 1
            if not ops:
                raise AsmError("wait pin P, v | wait change A[, B] | wait flag N, v")
            tmo = (tmo_reg << 10) | (tmo_en << 9)
            first = ops[0].split()
            kind = first[0]
            if kind == "pin" and n == 2:
                a = self._pin(first[1], write=False)
                return OP["wait"], (0 << 17) | (a << 13) | tmo | (self._val(ops[1], 1) << 8)
            if kind == "change" and n in (1, 2):
                a = self._pin(first[1], write=False)
                b = self._pin(ops[1], write=False) if n == 2 else a
                return OP["wait"], (1 << 17) | (a << 13) | tmo | (b << 4)
            if kind == "flag" and n == 2:
                f = self._val(first[1], 3)
                return OP["wait"], (2 << 17) | (f << 13) | tmo | (self._val(ops[1], 1) << 8)
            raise AsmError("wait pin P, v | wait change A[, B] | wait flag N, v   [, timeout rN]")

        if mnem in ("in", "out"):
            feed = 0
            if ops and ops[-1] == "feed":
                feed = 1
                ops = ops[:-1]
                n -= 1
            if n != 2:
                raise AsmError(f"{mnem} WHERE, bits [, feed]")
            bits = self._val(ops[1], 4)
            if not 1 <= bits <= 8:
                raise AsmError("bit count must be 1..8")
            where = ops[0]
            p = self._split_kw(where, "pin")
            if p is not None:
                kind, fld = 0, self._pin(p, write=(mnem == "out")) << 13
            elif where == "t":
                kind, fld = 1, 0
            elif _is_reg(where):
                kind, fld = 2, _reg(where) << 10
            elif where in ("zeros", "null"):
                kind, fld = 3, 0
            else:
                raise AsmError(f"{mnem}: unknown source or destination '{where}'")
            if kind in (0, 1) and bits != 1:
                raise AsmError("a pin or T takes exactly 1 bit")
            if feed and bits != 1:
                raise AsmError("feed needs a bit count of 1")
            op = OP["inp"] if mnem == "in" else OP["out"]
            return op, (kind << 17) | fld | (feed << 9) | ((bits - 1) << 6)

        if mnem in ("push", "pull"):
            flags = " ".join(ops).split()
            block = 0 if "noblock" in flags else 1
            only = 1 if ("iffull" in flags or "ifempty" in flags) else 0
            direction = 1 if mnem == "pull" else 0
            return OP["pp"], (direction << 18) | (block << 17) | (only << 16)

        if mnem in ("mov", "par", "nop"):
            if mnem == "nop":
                ops = ["null", "null"]
            elif mnem == "par":
                ops = ["null", ops[0], "par"]
            if len(ops) not in (2, 3):
                raise AsmError("mov DEST, SOURCE [, inv|rev|par]")
            dst_t, src_t = ops[0], ops[1]
            dst = _reg(dst_t) if _is_reg(dst_t) else MOV_DST.get(dst_t)
            src = _reg(src_t) if _is_reg(src_t) else MOV_SRC.get(src_t)
            if dst is None:
                raise AsmError(f"mov: unknown destination '{dst_t}'")
            if src is None:
                raise AsmError(f"mov: unknown source '{src_t}'")
            mop = 0
            if len(ops) == 3:
                if ops[2] not in MOV_OP:
                    raise AsmError("mov: third operand must be inv, rev or par")
                mop = MOV_OP[ops[2]]
            return OP["mov"], (mop << 17) | (src << 10) | (dst << 5)

        if mnem == "irq":
            if n != 1 or len(ops[0].split()) != 2:
                raise AsmError("irq set N | irq clear N | irq wait N")
            what, f = ops[0].split()
            code = {"set": 0, "clear": 1, "wait": 2}.get(what)
            if code is None:
                raise AsmError("irq set N | irq clear N | irq wait N")
            return OP["irq"], (code << 17) | (self._val(f, 3) << 13)

        if mnem == "set":
            if n != 2:
                raise AsmError("set rN, value | set pin P, v | set dir P, v")
            p = self._split_kw(ops[0], "pin")
            if p is not None:
                return OP["pin"], (0 << 17) | (self._pin(p, True) << 13) | (self._val(ops[1], 1) << 12)
            p = self._split_kw(ops[0], "dir")
            if p is not None:
                pin = self._pin(p, True)
                if pin < 8:
                    raise AsmError("only io0..io7 have a direction")
                return OP["pin"], (2 << 17) | (pin << 13) | (self._val(ops[1], 1) << 12)
            return OP["set"], (_reg(ops[0]) << 16) | self._val(ops[1], 16)

        if mnem == "toggle":
            p = self._split_kw(ops[0], "pin") if n == 1 else None
            if p is None:
                raise AsmError("toggle pin P")
            return OP["pin"], (1 << 17) | (self._pin(p, True) << 13)

        if mnem in ALU_FN:
            fn = ALU_FN[mnem]
            if mnem == "cmp":
                if n != 2:
                    raise AsmError("cmp rA, rB|value")
                rd, ra, b = 0, _reg(ops[0]), ops[1]
            else:
                if n != 3:
                    raise AsmError(f"{mnem} rD, rA, rB|value")
                rd, ra, b = _reg(ops[0]), _reg(ops[1]), ops[2]
            if _is_reg(b):
                return OP["alur"], (fn << 16) | (rd << 13) | (ra << 10) | (_reg(b) << 7)
            return OP["alui"], (fn << 16) | (rd << 13) | (ra << 10) | self._val(b, 10)

        if mnem in ("ld", "st"):
            if n != 2:
                raise AsmError(f"{mnem} rN, [rB] | [rB+off] | [@off]")
            use, base, off = self._mem(ops[1])
            reg = _reg(ops[0]) << (13 if mnem == "ld" else 7)
            return OP[mnem], reg | (base << 10) | (use << 6) | off

        if mnem in ("ldm", "stm"):
            # One byte of the engine's memory block, at the byte address in rB.
            m = re.fullmatch(r"\[\s*(r[0-7])\s*\]", ops[1]) if n == 2 else None
            if not m:
                raise AsmError(f"{mnem} rN, [rB]")
            reg = _reg(ops[0]) << (13 if mnem == "ldm" else 7)
            return OP["ld" if mnem == "ldm" else "st"], (1 << 18) | reg | (_reg(m.group(1)) << 10)

        if mnem == "call":
            if n != 1:
                raise AsmError("call label")
            return OP["call"], self._target(ops[0])
        if mnem == "ret":
            return OP["call"], 1 << 18
        if mnem == "halt":
            return OP["halt"], 0

        raise AsmError(f"unknown instruction '{mnem}'")

    def build(self):
        prog = Program(labels=dict(self.labels))
        for num, src, cond, mnem, ops, side, delay in self.items:
            try:
                op, operands = self._encode(mnem, list(ops))
            except AsmError as e:
                raise AsmError(f"line {num}: {e}\n    {src}") from None
            word = (op << 28) | (cond << 26) | (delay << 22) | operands
            if side is not None:
                word |= (1 << 21) | (side << 19)
            prog.words.append(word)
            prog.lines.append(src)
        return prog


def assemble(text):
    """Assemble source text. Returns a Program; raises AsmError on a mistake."""
    return _Asm(text).build()


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        prog = assemble(open(argv[1]).read())
    except AsmError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for addr, (word, src) in enumerate(zip(prog.words, prog.lines)):
        print(f"{addr:02x}: {word:08x}    {src}")
    print()
    for name, addr in sorted(prog.labels.items(), key=lambda kv: kv[1]):
        print(f"{name} = 0x{addr:02x}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
