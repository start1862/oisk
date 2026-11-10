#!/usr/bin/env python3
"""MM allocator regression for the OISC kernel port.

Compiles kernel/t_mm.c (single TU: it #includes arch/oisc/mm/alloc.c through
the preprocessor, exactly like the real `oscc.py -I... t_mm.c` build), runs it
on the simulator and checks the free-list allocator semantics:

  - mm_init creates one free block
  - 8 allocations carve contiguous pages at 0x10000000..0x10007000
  - the 9th allocation fails (pool exhausted)
  - freeing p2/p5 creates two holes (free_count 2)
  - re-allocation reuses the holes (both non-zero, pool exhausted again)
  - alloc/free counters hold
"""
import os
import sys
sys.path.insert(0, '/opt/oisk')
from oscc import tokenize, Parser, CodeGen
from osma import Asm
from sim import Sim
from preproc import preprocess

KROOT = '/opt/oisk/kernel'
INCS = [KROOT + '/arch/oisc/include']

def main():
    path = os.path.join(KROOT, 't_mm.c')
    src = open(path).read()
    pp = preprocess(src, path, INCS)
    p = Parser(tokenize(pp))
    decls = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(decls)
    words = cg.build()
    print('compiled: %d words (%d bytes)' % (len(words), len(words) * 4))

    s = Sim()
    s.load_words(words)
    n = s.run(max_steps=5000000)
    print('sim steps=%d halted=%s' % (n, s.halted))

    g = cg.a.globs
    def gv(name):
        return s.mem[g['__g_g_' + name][1]]

    exp = {
        'p0': 0x10000000, 'p1': 0x10001000, 'p2': 0x10002000,
        'p3': 0x10003000, 'p4': 0x10004000, 'p5': 0x10005000,
        'p6': 0x10006000, 'p7': 0x10007000, 'p8': 0,
        'free0': 1, 'free1': 0, 'free2': 2, 'free3': 0,
        'alloc1': 8, 'alloc2': 10, 'fail': 0,
    }
    ok = True
    for nm, want in exp.items():
        got = gv(nm)
        good = (got == want)
        ok = ok and good
        print('  %-8s got=0x%-8x want=0x%-8x %s'
              % (nm, got, want, 'OK' if good else 'FAIL'))
    r1 = gv('r1'); r2 = gv('r2')
    reuse_ok = (r1 != 0 and r2 != 0)
    ok = ok and reuse_ok
    print('  r1=0x%x r2=0x%x (hole reuse) -> %s' % (r1, r2,
          'OK' if reuse_ok else 'FAIL'))
    print('RESULT:', 'OK' if ok else 'FAIL')
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()