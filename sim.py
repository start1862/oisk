#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Strict QEMU-compatible SUBLEQ simulator.

Semantics (matches target/oisc/translate.c trans_subleq):
  va = mem[a]; vb = mem[b]; res = vb - va; mem[b] = res;
  if res <= 0: pc = c;  if c == 0 or c has sign bit -> halt
  else: pc += 4

Cells: 4 words [A B C pad], pc is a WORD address advancing by 4.
Firmware is a flat little-endian word image loaded at RAM word 0.
"""
import struct
import sys

RAM_WORDS = 64 * 1024 * 1024 // 4   # 64 MiB


class Sim:
    def __init__(self, fw_words=None, ram_words=RAM_WORDS):
        self.mem = [0] * ram_words
        self.pc = 0
        self.halted = False
        self.out = bytearray()
        self.disk = bytearray()      # virtual disk image (oisk_hd.bin)
        self._cmd = 0
        self._disk_stage = 0
        self._disk_buf = 0
        if fw_words:
            self.mem[:len(fw_words)] = fw_words

    def load_bin(self, path):
        d = open(path, 'rb').read()
        w = list(struct.unpack('<%dI' % (len(d) // 4), d))
        self.mem[:len(w)] = w
        return len(w)

    def load_words(self, words):
        """Load a flat list of 32-bit words at RAM word 0."""
        if isinstance(words, bytes):
            words = list(struct.unpack('<%dI' % (len(words) // 4), words))
        self.mem[:len(words)] = [w & 0xffffffff for w in words]
        return len(words)

    # MMIO word addresses (from oishw)
    W_TX = 0x3FFFC000
    W_RX = 0x3FFFC001
    W_CMD = 0x3FFFC002
    W_DAT = 0x3FFFC003
    W_RES = 0x3FFFC005
    W_CLK = 0x3FFFC007
    W_MX = 0x3FFFC009
    W_MY = 0x3FFFC00A
    W_MB = 0x3FFFC00B
    W_DISK = 0x3FFFC00D

    def mmio_read(self, w):
        if w == self.W_RX:
            return 0
        if w == self.W_RES:
            return 0
        if w == self.W_CLK:
            return 0
        if w == self.W_MX or w == self.W_MY or w == self.W_MB:
            return 0
        return 0   # TX etc read 0

    def mmio_write(self, w, val):
        v = val & 0xffffffff
        if w == self.W_TX:
            self.out.append(v & 0xff)
        elif w == self.W_CMD:
            # GPU/DISK command word.  GPU cmd 14 = DISK bufword op:
            #   write CMD=14, then DAT=bufword, then DAT=op
            #   op = lba | (nsec << 16) | (dir << 24), dir 1 = read to guest
            self._cmd = v
            self._disk_stage = 0
        elif w == self.W_DAT:
            if getattr(self, '_cmd', None) == 14:
                if getattr(self, '_disk_stage', 0) == 0:
                    self._disk_buf = v
                    self._disk_stage = 1
                elif self._disk_stage == 1:
                    self._disk_stage = 0
                    self._disk_exec(self._disk_buf, v)
        # W_DISK direct op write: not the ko path (ko uses CMD/DAT)

    def load_disk(self, path):
        self.disk = bytearray(open(path, 'rb').read())
        return len(self.disk)

    def _disk_exec(self, bufword, op):
        """Execute a DISK command (GPU cmd 14).
        op = lba | (nsec << 16) | (dir << 24), dir 1 = read to guest.
        Reads nsec sectors (512B each) from LBA lba into guest RAM words
        starting at word address bufword.  Each sector is 128 words."""
        nsec = (op >> 16) & 0xff
        lba = op & 0xffff
        direc = (op >> 24) & 0xff
        if direc != 1 or not self.disk:
            return
        start = lba * 512
        for sec in range(nsec):
            off = start + sec * 512
            src = self.disk[off:off + 512]
            if len(src) < 512:
                src += b'\0' * (512 - len(src))
            words = list(struct.unpack('<128I', src))
            base = bufword + sec * 128
            for i, w in enumerate(words):
                if base + i < len(self.mem):
                    self.mem[base + i] = w & 0xffffffff

    def step(self):
        pc = self.pc
        a = self.mem[pc]
        b = self.mem[pc + 1]
        c = self.mem[pc + 2]
        va = self.mem[a] if a < len(self.mem) else self.mmio_read(a)
        vb = self.mem[b] if b < len(self.mem) else self.mmio_read(b)
        res = (vb - va) & 0xffffffff
        if b < len(self.mem):
            self.mem[b] = res
        else:
            self.mmio_write(b, res)
        # REAL QEMU semantics (translate.c trans_subleq):
        #   tcg_gen_sub_i32(res, vb, va);
        #   do_branch_dyn(TCG_COND_LE, res, c)  -- SIGNED <= 0
        # Jump iff (res as signed 32-bit) <= 0.  On branch taken:
        #   gen_jump_dyn: halt iff C == 0 or C has sign bit set.
        res_signed = res if res < 0x80000000 else res - 0x100000000
        if res_signed <= 0:
            if c == 0 or (c & 0x80000000):
                self.halted = True
            else:
                self.pc = c
        else:
            self.pc = pc + 4

    def run(self, max_steps=100000000, trace=False, trace_to=None):
        n = 0
        while not self.halted and n < max_steps:
            if trace:
                pc = self.pc
                a = self.mem[pc]; b = self.mem[pc + 1]; c = self.mem[pc + 2]
                va = self.mmio_read(a) if a >= len(self.mem) else self.mem[a]
                vb = self.mmio_read(b) if b >= len(self.mem) else self.mem[b]
                line = 'pc=%06x A=%08x B=%08x C=%08x  memA=%08x memB=%08x\n' % (
                    pc, a, b, c, va, vb)
                if trace_to:
                    trace_to.write(line)
                else:
                    print(line, end='')
            self.step()
            n += 1
        return n

    def tell(self, reg_first_word):
        pass


if __name__ == '__main__':
    s = Sim()
    s.load_bin(sys.argv[1])
    n = s.run(trace=('-t' in sys.argv))
    print('\n--- sim: %d steps, halted=%s, pc=%x' % (n, s.halted, s.pc))
    print('out:', s.out.decode(errors='replace'))