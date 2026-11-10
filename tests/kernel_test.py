#!/usr/bin/env python3
"""Kernel-tree regression for OSCC: compiles arch/oisc sources through the
full pipeline (preprocess -> tokenize -> parse -> codegen -> simulate) and
verifies the architectural constants/semantics they encode.

Each case mirrors a real build of arch/oisc/{lib,mm,kernel}/*.c as driven
by `oscc.py -Ikernel/arch/oisc/include ...`.
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

results = []


def build_c(relpath, checks, max_steps=600000):
    path = os.path.join(KROOT, relpath)
    src = open(path).read()
    pp = preprocess(src, path, INCS)
    p = Parser(tokenize(pp))
    decls = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(decls)
    words = cg.build()
    s = Sim()
    s.load_words(words)
    steps = s.run(max_steps=max_steps)
    ok = True
    for nm, want in checks:
        ad = cg.a.globs['__g_' + nm][1]
        got = s.mem[ad]
        good = got == want
        ok = ok and good
        print('  %-12s got=%-12d want=%-12d %s'
              % (nm, got, want, 'OK' if good else 'FAIL'))
    print('  steps=%d halted=%s -> %s' % (steps, s.halted,
                                          'OK' if ok else 'FAIL'))
    return ok


# 1. types.h / oisc_hw.h constants resolution
print('[hw_constants] t_hw.c')
results.append(('hw_constants', build_c('t_hw.c', [
    ('g_page', PAGE := 4096),
    ('g_mask', 0xfffff000),
    ('g_flags', 2),           # OISC_FLAGS fixed word
    ('g_timer', 0x101004),    # OISC_TIMER_COMPARE
    ('g', (PAGE + 2 + 0x101004)),
])))

# 2. irq.h arch_local_irq_* semantics (flags read back)
print('[irq_flags] t_irq.c')
results.append(('irq_flags', build_c('t_irq.c', [
    ('g1', 0),   # saved after disable
    ('g2', 1),   # after enable
    ('g3', 0),   # after disable again
])))

# 3. lib/delay.c: compile-only (no runnable main; verify it builds)
def t_delay_compiles():
    path = os.path.join(KROOT, 'arch/oisc/lib/delay.c')
    src = open(path).read()
    pp = preprocess(src, path, INCS)
    p = Parser(tokenize(pp))
    d = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(d)
    w = cg.build()
    return len(w) > 0

print('[delay_compiles] arch/oisc/lib/delay.c')
try:
    ok = t_delay_compiles()
    print('  %s' % ('OK' if ok else 'FAIL'))
except Exception as e:
    print('  EXC %s: %s' % (type(e).__name__, e))
    ok = False
results.append(('delay_compiles', ok))


# 4. lib/memcpy.c: compile + actually copy 4 words and sum them
def t_memcpy_runs():
    lib = open(os.path.join(KROOT, 'arch/oisc/lib/memcpy.c')).read()
    tst = open(os.path.join(KROOT, 't_memcpy.c')).read()
    # single translation unit: OSCC has no separate linker, so the test is
    # merged with the library source it exercises.
    merged = lib + '\n' + tst
    pp = preprocess(merged, '<memcpy_test>', INCS)
    p = Parser(tokenize(pp))
    d = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(d)
    s = Sim()
    s.load_words(cg.build())
    steps = s.run(max_steps=2000000)
    got = s.mem[cg.a.globs['__g_g_sum'][1]]
    print('  g_sum        got=%-12d want=%-12d %s'
          % (got, 10, 'OK' if got == 10 else 'FAIL'))
    print('  steps=%d halted=%s' % (steps, s.halted))
    return got == 10

print('[memcpy_copies] arch/oisc/lib/memcpy.c')
try:
    ok = t_memcpy_runs()
    print('  %s' % ('OK' if ok else 'FAIL'))
except Exception as e:
    print('  EXC %s: %s' % (type(e).__name__, e))
    ok = False
results.append(('memcpy_copies', ok))


# 5. cache.h / cacheflush.h: no-op flush functions + L1_CACHE_BYTES
def t_cache_runs():
    src = open(os.path.join(KROOT, 't_cache.c')).read()
    pp = preprocess(src, '<cache_test>', INCS)
    p = Parser(tokenize(pp))
    d = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(d)
    s = Sim()
    s.load_words(cg.build())
    steps = s.run(max_steps=50000)
    ok = True
    for nm, want in (('g_l1', 1), ('g_done', 1)):
        got = s.mem[cg.a.globs['__g_' + nm][1]]
        good = got == want
        ok = ok and good
        print('  %-10s got=%-8d want=%-8d %s'
              % (nm, got, want, 'OK' if good else 'FAIL'))
    print('  steps=%d halted=%s -> %s' % (steps, s.halted,
                                          'OK' if ok else 'FAIL'))
    return ok

print('[cache_flush] t_cache.c')
try:
    ok = t_cache_runs()
    print('  %s' % ('OK' if ok else 'FAIL'))
except Exception as e:
    print('  EXC %s: %s' % (type(e).__name__, e))
    ok = False
results.append(('cache_flush', ok))

# 6. mm/alloc.c: free-list page allocator (alloc, free, hole reuse, exhaustion)
def t_mm_runs():
    # single TU: t_mm.c #includes arch/oisc/mm/alloc.c
    src = open(os.path.join(KROOT, 't_mm.c')).read()
    pp = preprocess(src, os.path.join(KROOT, 't_mm.c'), INCS)
    p = Parser(tokenize(pp))
    d = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(d)
    s = Sim()
    s.load_words(cg.build())
    steps = s.run(max_steps=5000000)
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
    print('  steps=%d halted=%s' % (steps, s.halted))
    return ok
print('[mm_alloc] arch/oisc/mm/alloc.c')
try:
    ok = t_mm_runs()
    print('  %s' % ('OK' if ok else 'FAIL'))
except Exception as e:
    print('  EXC %s: %s' % (type(e).__name__, e))
    ok = False
results.append(('mm_alloc', ok))

passed = sum(1 for _, ok in results if ok)
total = len(results)
print('TOTAL: %d/%d %s' % (passed, total,
                           'ALL PASS' if passed == total else 'FAILURES'))
sys.exit(0 if passed == total else 1)