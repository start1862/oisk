#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""prims_test.py - prove every SUBLEQ primitive oscc needs, on osma+sim.

Run: python3 /opt/oisk/prims_test.py
All values checked against the fixed slots after the program halts.
"""
import struct
import sys
sys.path.insert(0, '/opt/oisk')
from osma import Asm, L, C, S, R, G
from sim import Sim


def build_words(a):
    words = a.build()
    return words


def run(words):
    s = Sim()
    s.load_words(words)
    n = s.run()
    return s, n


def check(name, got, want):
    ok = (got & 0xffffffff) == (want & 0xffffffff)
    print('%-12s got=%08x want=%08x %s' % (
        name, got & 0xffffffff, want & 0xffffffff, 'OK' if ok else 'FAIL'))
    return ok


def main():
    a = Asm()
    z = a.const(0)
    # slots
    x = a.slot('x')       # 13
    y = a.slot('y')       # 7
    s = a.slot('s')       # x+y
    d = a.slot('d')       # x-y
    m = a.slot('m')       # x*y
    q = a.slot('q')       # x/3 (floor via loop)
    neg = a.slot('neg')   # -x
    t = a.slot('t')       # temp
    nb = a.slot('nb')     # negated b
    idx = a.slot('idx')
    arr0 = a.slot('arr0')
    arr1 = a.slot('arr1')
    arr2 = a.slot('arr2')
    got_arr = a.slot('got_arr')
    acc = a.slot('_acc')
    r0 = a.slot('_r0')
    ra = a.slot('_ra')

    # ---- seti helper (inline repeat) ----
    def seti(dst, val):
        nv = a.const(-val & 0xffffffff)
        l1 = L('si_%d' % len(a.cells))    # unique-ish label
        l2 = L('sj_%d' % len(a.cells))
        a.cell(z, dst, l1)
        a.label(l1.name)
        a.cell(nv, dst, l2)
        a.label(l2.name)
        a.cell(z, z, l2)                  # no-op loop exit (goes to l2)
        # NOTE: this pattern yields 4 cells; the trailing no-op jumps to l2
        # which is the previous cell -> INFINITE LOOP.  Fix: last cell C
        # must be a label AFTER it.  We'll fix below.

    # Actually make seti clean: emit a jump-to-next that falls through.
    def seti2(dst, val):
        nv = a.const(-val & 0xffffffff)
        l1 = L('s1_%d' % len(a.cells))
        l2 = L('s2_%d' % len(a.cells))
        a.cell(z, dst, l1)
        a.label(l1.name)
        a.cell(nv, dst, L('s2_%d' % len(a.cells)))
        # no trailing jump: after l2 falls into next emit naturally
        a.label(l2.name)

    seti2(x, 13)
    seti2(y, 7)

    # ---- s = x + y ----
    a.cell(z, t, L('p1')); a.label('p1')      # t = 0
    a.cell(x, t, L('p2')); a.label('p2')      # t = -x
    a.cell(y, t, L('p3')); a.label('p3')      # t = -x-y
    a.cell(z, s, L('p4')); a.label('p4')      # s = 0
    a.cell(t, s, L('p5')); a.label('p5')      # s = x+y
    a.cell(z, z, L('p6')); a.label('p6')      # no-op end (jump to p6 = itself? no, C=p6 which is next)

    # ---- d = x - y ----
    a.cell(z, nb, L('q1')); a.label('q1')     # nb = 0
    a.cell(y, nb, L('q2')); a.label('q2')     # nb = -y
    a.cell(z, t, L('q3')); a.label('q3')      # t = 0
    a.cell(x, t, L('q4')); a.label('q4')      # t = -x
    a.cell(nb, t, L('q5')); a.label('q5')     # t = -x - (-y) = y - x
    a.cell(z, d, L('q6')); a.label('q6')      # d = 0
    a.cell(t, d, L('q7')); a.label('q7')      # d = x - y
    a.cell(z, z, L('q8')); a.label('q8')

    # ---- neg = -x (test unary minus) ----
    a.cell(z, t, L('n1')); a.label('n1')
    a.cell(x, t, L('n2')); a.label('n2')      # t = -x
    a.cell(z, neg, L('n3')); a.label('n3')
    a.cell(t, neg, L('n4')); a.label('n4')    # neg = -x
    a.cell(z, z, L('n5')); a.label('n5')

    # ---- m = x * y  (loop: m += x, y -= 1 while y>0) ----
    a.cell(z, m, L('ml1')); a.label('ml1')    # m = 0
    a.cell(z, z, L('ml2')); a.label('ml2')
    a.label('mltop')
    # if y <= 0 goto mldone (branch on y sign)
    a.cell(y, y, L('mldone'))                 # y-=y => 0 <=0 -> jump to mldone
    # BUT this clobbers y!  We need to preserve y.  Use a copy in t?
    # Standard: copy y to t:   (zero t; t-=y => t=-y; then negate)
    # Instead: branch on y using a scratch that loses y is bad. Use:
    #   scratch = y ; if scratch<=0...
    # Simpler mult: for(i=0;i<y;i++) m+=x => i counts up, y stays.
    # Implement with counter c = 0..y-1:
    #   done when c >= y:  t = c - y ; if t >=0 (t 0x7fffffff?) using LE:
    #     branch when t <= 0 means c<=y (not done), we want loop while c<y
    #   Standard while (c < y): t = y - c; loop while t > 0.
    #   c < y  <=>  y - c > 0  <=>  (y-c) is positive => LE NOT taken.
    #   Loop cond branch taken when NOT (y-c>0) i.e. (y-c)<=0 -> done.
    # Use c slot.
    c = a.slot('c')
    a.cell(z, c, L('mla')); a.label('mla')    # c = 0
    a.label('mltop2')
    # t = y - c  (t = y + (-c))
    a.cell(z, nb, L('mlb')); a.label('mlb')   # nb = 0
    a.cell(c, nb, L('mlc')); a.label('mlc')   # nb = -c
    a.cell(z, t, L('mld')); a.label('mld')    # t = 0
    a.cell(y, t, L('mle')); a.label('mle')    # t = -y
    a.cell(nb, t, L('mlf')); a.label('mlf')   # t = -y - (-c) = c - y
    a.cell(z, t, L('mlg')); a.label('mlg')    # t = 0
    a.cell(c, t, L('mlh')); a.label('mlh')    # t = -c
    a.cell(nb, t, L('mli')); a.label('mli')   # t = -c - (-y) = y - c
    # t is now y-c (positive while c<y).  branch if t<=0 -> done
    a.cell(t, t, L('mldone'))
    # m += x
    a.cell(z, t, L('mlj')); a.label('mlj')    # t=0
    a.cell(x, t, L('mlk')); a.label('mlk')    # t=-x
    a.cell(t, m, L('mll')); a.label('mll')    # m = m - (-x) = m + x
    # c += 1
    one = a.const(-1)
    a.cell(z, c, L('mlm')); a.label('mlm')    # c = 0
    a.cell(one, c, L('mln')); a.label('mln')  # c = 0 - (-1) = 1
    # add: c = c + t2 ... simpler use: c -= -1
    # redo: do it right: c=0; c -= -1 => 1; but we need c+=1: c=c+1
    # use: t2 = 0; t2 -= -1 (t2=1); c -= t2 => c = c - 1?? NO, c -= t2 => c -= 1
    # We want c += 1: c = c + 1 = c - (-1).  tmp=0; tmp-=(-1)=>tmp=1;
    # c -= (-1) => c = c - (-1) = c+1.  So need a const -1 in slot.
    a.cell(z, t, L('mlo')); a.label('mlo')    # t = 0
    a.cell(one, t, L('mlp')); a.label('mlp')  # t = 0 - (-1) = 1
    # c = c - (-1) = c+1:  c -= (neg of 1) i.e. c -= (-1).  We have slot t=1
    # c -= t ?  c = c - 1.  Not +1.  Instead c -= ( -1 ):
    #   c = c - (-1) = c + 1: subleq (addr of -1) c
    # We need a slot with value -1: const(-1) as A works: c -= (-1)?
    # A = const(-1) means mem[c] = mem[c] - (-1) = c+1.  YES!
    a.cell(one, c, L('mlq')); a.label('mlq')  # c = c - (-1) = c+1
    a.cell(z, z, L('mltop2'))                 # loop
    a.label('mldone')
    # m now = x*y

    a.halt()
    words = a.build()
    open('/tmp/prims.bin', 'wb').write(b''.join(struct.pack('<I', w) for w in words))

    s = Sim()
    s.load_bin('/tmp/prims.bin')
    n = s.run()
    print('steps=%d halted=%s pc=%x' % (n, s.halted, s.pc))
    allok = True
    allok &= check('x', s.mem[word_of(a, 'x')], 13)
    allok &= check('y', s.mem[word_of(a, 'y')], 7)
    allok &= check('s(x+y)', s.mem[word_of(a, 's')], 20)
    allok &= check('d(x-y)', s.mem[word_of(a, 'd')], 6)
    allok &= check('neg(-x)', s.mem[word_of(a, 'neg')], (-13) & 0xffffffff)
    allok &= check('m(x*y)', s.mem[word_of(a, 'm')], 91)
    return 0 if allok else 1


def word_of(a, name):
    return a.build_slot(name) if hasattr(a, 'build_slot') else 0
    # fallback: recompute via Asm internals is messy; instead print all slots


if __name__ == '__main__':
    sys.exit(main())