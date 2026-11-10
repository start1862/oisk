#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""osma.py - clean SUBLEQ assembler for OISC.

Semantics: 4-word cell [A B C pad]; pc advances by 4 words per cell.
  subleq A,B,C:  mem[B] -= mem[A]; if mem[B] <= 0 then PC=C
                (C==0 or C sign-bit set halts) else PC=PC+4.

Operands are WORD addresses.  Immediates live in a constant pool: const(v)
returns the address of a word containing v.  Scratch cells are slots.
Registers are absolute MMIO word addresses from oishw.

C field defaults to fall-through (address of the next cell).  jump = subleq
Z,Z,target (Z points to a zero word); halt = subleq Z,Z,0.

Layout: cells (4 words each) then constant pool then slots, each
1 word per entry at 4-word alignment.  All symbol resolution produces
absolute word addresses.
"""
import struct


class Sym:
    __slots__ = ('kind', 'name')

    def __init__(self, kind, name):
        self.kind = kind
        self.name = name

    def __repr__(self):
        return '%s:%s' % (self.kind, self.name)


def L(name): return Sym('L', name)   # label
def C(v):    return Sym('C', v)      # constant value
def S(name): return Sym('S', name)   # slot name
def R(name): return Sym('R', name)   # mmio register name (eg 'TX')
def G(name): return Sym('G', name)   # global data array base


class Asm:
    def __init__(self, base=0):
        self.base = base
        self.cells = []          # list of [a, b, c] (int or Sym)
        self.labels = {}         # name -> word offset (module-relative)
        self._pos = 0            # next cell offset in words
        self._consts = {}        # value -> None (alloc order)
        self._slots = {}         # name -> None (alloc order)
        self.globs = {}          # name -> (nwords, None) alloc order
        self.glob_order = []     # names in alloc order
        self._fixed = {}         # name -> value (hand-assigned symbols)
        self._aconsts = []       # (sym, negate) -> const whose WORD VALUE is ±addr
        self._faddr = []         # (sym, off) -> DIRECT numeric addr (=addr+off),
                                 # embedded raw into cell field (no const pool)

    def here(self):
        return self.base + self._pos

    def label(self, name):
        self.labels[name] = self._pos
        return self

    # ---- operands ----
    def const(self, value):
        value &= 0xffffffff
        if value not in self._consts:
            self._consts[value] = None
        return C(value)

    def slot(self, name):
        if name not in self._slots:
            self._slots[name] = None
        return S(name)

    def glob(self, name, nwords=1):
        """Allocate nwords contiguous data words; returns base address Sym."""
        if name not in self.globs:
            self.globs[name] = nwords
            self.glob_order.append(name)
        return G(name)

    def reg(self, name):
        return R(name)

    def fixed(self, name, value):
        self._fixed[name] = value & 0xffffffff
        return C(name)

    def addr_of(self, sym, negate=False):
        """Allocate a const pool entry whose WORD VALUE is the resolved
        absolute address of `sym` (label/slot/glob/reg/const), optionally
        negated.  Resolution is deferred to build() time."""
        self._aconsts.append((sym, bool(negate)))
        return C(('A', len(self._aconsts) - 1))

    def addr_off(self, sym, off, negate=False):
        """Like addr_of but the const value is addr-of-sym + off.

        Shares the same 'A' const namespace as addr_of (the resolved value
        is computed in build()) so callers can treat both identically."""
        self._aconsts.append((sym, bool(negate), int(off)))
        return C(('A', len(self._aconsts) - 1))

    def field_addr(self, sym, off=0):
        """Return a Sym('F', (idx, off)) that resolves DIRECTLY to the
        absolute numeric address addr(sym)+off at build time -- the value
        is embedded RAW into the cell field (no const pool indirection).

        Used for writing SELF-MODIFYING trampoline cells: we need the
        actual code address, not a const pool word that merely holds it."""
        self._faddr.append((sym, int(off)))
        return C(('F', len(self._faddr) - 1))

    # ---- emission ----
    def cell(self, a, b, c=None):
        ca = self._addr(a)
        cb = self._addr(b)
        if c is None:
            cc = self.base + self._pos + 4      # absolute addr of next cell
        else:
            cc = self._addr(c)
        self.cells.append([ca, cb, cc])
        self._pos += 4
        return self

    def _addr(self, x):
        if isinstance(x, Sym):
            return x
        if isinstance(x, int):
            return C(x)
        raise ValueError('bad operand %r' % x)

    def sq(self, a, b, c=None):
        return self.cell(a, b, c)

    def jmp(self, target):
        z = self.const(0)
        return self.cell(z, z, self._addr(target))

    def halt(self):
        z = self.const(0)
        return self.cell(z, z, C(0))

    def mmio_w(self, reg, value):
        """reg = value. subleq const(-value), reg, nextcell.
        mem[reg] reads 0 (MMIO), res = 0 - (-value) = value, write reg,
        res>0 so C (next cell) is used only if res<=0 -> never; falls
        through naturally via PC+4."""
        return self.cell(self.const(-value), self.reg(reg))

    def putc(self, ch):
        v = ord(ch)
        return self.cell(self.const(-v), self.reg('TX'))

    def puts(self, s, nl=True):
        for ch in s:
            self.putc(ch)
        if nl:
            self.putc('\n')
        return self

    # ---- resolution ----
    def build(self, extern_labels=None):
        if extern_labels:
            for k, v in extern_labels.items():
                self._fixed[k] = v
        tail = self._pos

        # label/slot/glob absolute addresses (needed for addr_of consts)
        laddr = {name: self.base + off for name, off in self.labels.items()}

        def base_addr(x):
            if isinstance(x, Sym):
                if x.kind == 'L':
                    if x.name in laddr:
                        return laddr[x.name]
                    if x.name in self._fixed:
                        return self._fixed[x.name]
                    raise KeyError('unknown label %s' % x.name)
                if x.kind == 'S':
                    if x.name in self._slots:
                        return self._slots[x.name]
                    raise KeyError('unknown slot %s' % x.name)
                if x.kind == 'R':
                    import oishw
                    w = getattr(oishw, 'W_' + x.name, None)
                    if w is None:
                        raise KeyError('unknown reg %s' % x.name)
                    return w
                if x.kind == 'G':
                    if x.name in self.globs:
                        return self.globs[x.name][1]
                    raise KeyError('unknown global %s' % x.name)
                if x.kind == 'C':
                    if isinstance(x.name, tuple) and x.name[0] in ('A', 'AO'):
                        # nested addr const: value = aconst_vals[idx] if
                        # already computed, else deferred (raise -> caller
                        # must not use addr const as a base for another
                        # addr const before it's finalised).  For our uses
                        # (set_addr tplC etc.) the target is a plain
                        # label/slot/glob, so this only triggers for real
                        # nesting which we avoid.
                        i = x.name[1]
                        if i < len(aconst_vals):
                            return aconst_vals[i]
                        raise ValueError('addr const %d not finalised' % i)
                    if x.name in self._consts:
                        return self._consts[x.name]
                    if x.name in self._fixed:
                        return self._fixed[x.name]
                    raise KeyError('unknown const %s' % (x.name,))
                raise ValueError('bad sym %r' % x)
            if isinstance(x, int):
                return x & 0xffffffff
            raise ValueError('bad operand %r' % x)

        # allocate const pool (plain ints first)
        cur = tail
        for v in self._consts:
            self._consts[v] = self.base + cur
            cur += 4
        # allocate slots
        for name in self._slots:
            self._slots[name] = self.base + cur
            cur += 4
        # allocate globals
        for name in self.glob_order:
            size = self.globs[name]
            self.globs[name] = (size, self.base + cur)
            cur += size
        total = cur

        aconst_vals = []
        for entry in self._aconsts:
            if len(entry) == 3:
                sym, negate, off = entry
            else:
                sym, negate = entry
                off = 0
            a = base_addr(sym)
            if negate:
                a = (-a) & 0xffffffff
            a = (a + off) & 0xffffffff
            aconst_vals.append(a)
            self._consts[('A', len(aconst_vals) - 1)] = None

        # give 'A' consts their addresses now (they were added after slots)
        for i in range(len(aconst_vals)):
            if self._consts[('A', i)] is None:
                self._consts[('A', i)] = self.base + cur
                cur += 4
        total = cur

        def fix(x):
            if isinstance(x, int):
                return x & 0xffffffff
            if isinstance(x, Sym):
                if x.kind == 'L':
                    if x.name in laddr:
                        return laddr[x.name]
                    if x.name in self._fixed:
                        return self._fixed[x.name]
                    raise KeyError('unknown label %s' % x.name)
                if x.kind == 'S':
                    if x.name in slot_addr:
                        return slot_addr[x.name]
                    raise KeyError('unknown slot %s' % x.name)
                if x.kind == 'R':
                    import oishw
                    w = getattr(oishw, 'W_' + x.name, None)
                    if w is None:
                        raise KeyError('unknown reg %s' % x.name)
                    return w
                if x.kind == 'G':
                    if x.name in glob_addr:
                        return glob_addr[x.name]
                    raise KeyError('unknown global %s' % x.name)
                if x.kind == 'C':
                    if isinstance(x.name, tuple) and x.name[0] == 'F':
                        # DIRECT field addr: raw numeric addr of sym+off
                        i = x.name[1]
                        sym, soff = self._faddr[i]
                        a = base_addr(sym) + soff
                        return a & 0xffffffff
                    if isinstance(x.name, tuple) and x.name[0] == 'A':
                        i = x.name[1]
                        if i < len(aconst_vals) and self._consts.get(('A', i)):
                            return self._consts[('A', i)]
                        raise KeyError('addr const %d' % i)
                    if x.name in self._consts:
                        return self._consts[x.name]
                    if x.name in self._fixed:
                        return self._fixed[x.name]
                    raise KeyError('unknown const %s' % x.name)
                raise ValueError('bad sym %r' % x)
            raise ValueError('bad operand %r' % x)

        # slot/glob absolute address maps (used by fix and tdata)
        slot_addr = {name: v for name, v in self._slots.items()}
        glob_addr = {name: v[1] for name, v in self.globs.items()}

        words = []
        for cell in self.cells:
            words += [fix(cell[0]), fix(cell[1]), fix(cell[2]), 0]
        tdata = [0] * (total - tail)
        for v, addr in self._consts.items():
            if isinstance(v, tuple) and v[0] == 'A':
                val = aconst_vals[v[1]]
            else:
                val = v
            tdata[addr - (self.base + tail)] = val & 0xffffffff
        words += tdata
        return words


def write_words(path, words):
    with open(path, 'wb') as f:
        for w in words:
            f.write(struct.pack('<I', w & 0xffffffff))


if __name__ == '__main__':
    a = Asm()
    a.puts('hello')
    a.halt()
    words = a.build()
    write_words('/tmp/osma_hello.bin', words)
    print('wrote /tmp/osma_hello.bin, %d words' % len(words))
    import subprocess
    r = subprocess.run(['python3', '/opt/oisk/sim.py', '/tmp/osma_hello.bin'],
                       capture_output=True, text=True)
    print(r.stdout)
    if r.returncode:
        print(r.stderr)