#!/usr/bin/env python3
"""End-to-end pipeline test: preprocess -> tokenize -> parse -> codegen -> sim.

This is the first test that goes through the FULL compile_c-style pipeline
(pre=True), exercising #include (with guards), object/function macros, and
conditional compilation combined with struct arrays and scaled indexing.
"""
import os
import sys
import tempfile

sys.path.insert(0, '/opt/oisk')
from oscc import tokenize, Parser, CodeGen
from preproc import preprocess
from osma import Asm
from sim import Sim

HDR = '''#ifndef _FLAGS_H
#define _FLAGS_H
#define BASE 100
#define WRAP(n) (BASE + (n))
#define SCALE_ARRAY 2
typedef struct { int a; int b; } Pair;
#endif
'''

MAIN = '''#include "flags.h"
#include "flags.h"

#define SET_G(v) g = (v)

Pair arr[3];
int g;
int h;

int main(){
    arr[0].a = WRAP(1);
    arr[0].b = WRAP(2);
    arr[1].a = WRAP(3);
    arr[1].b = WRAP(4);

#if SCALE_ARRAY == 2
    SET_G(arr[0].a + arr[1].b);
#else
    SET_G(1);
#endif

#ifdef NOT_DEFINED
    h = 9999;
#else
    h = arr[0].b - arr[1].a;
#endif
    return 0;
}
'''

results = []


def signed(v):
    return v - 2 ** 32 if v >= 2 ** 31 else v


def run_pipeline(src, cur_file, include_paths, checks, maxst=500000):
    pre = preprocess(src, cur_file, include_paths)
    p = Parser(tokenize(pre))
    decls = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(decls)
    words = cg.build()
    s = Sim()
    s.load_words(words)
    s.run(max_steps=maxst)
    ok = True
    for nm, want in checks:
        got = signed(s.mem[cg.a.globs['__g_' + nm][1]])
        good = got == want
        ok = ok and good
        print('  %-8s got %-8d want %-8d %s' % (nm, got, want,
                                                'OK' if good else 'FAIL'))
    return ok


def t_pipeline():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, 'flags.h'), 'w') as f:
        f.write(HDR)
    main = os.path.join(d, 'main.c')
    with open(main, 'w') as f:
        f.write(MAIN)
    return run_pipeline(MAIN, main, [d, '.'], [('g', 205), ('h', -1)])


def t_double_include_guard():
    """The header must be included only once despite two #include lines."""
    d = tempfile.mkdtemp()
    with open(os.path.join(d, 'flags.h'), 'w') as f:
        f.write(HDR)
    main = os.path.join(d, 'main.c')
    with open(main, 'w') as f:
        f.write(MAIN)
    pre = preprocess(MAIN, main, [d])
    # 'typedef struct' must appear exactly once in the preprocessed text
    return pre.count('typedef') == 1


for nm, fn in [('full_pipeline', t_pipeline),
               ('include_guard_once', t_double_include_guard)]:
    try:
        ok = fn()
    except Exception as e:
        print('%-22s EXC %s: %s' % (nm, type(e).__name__, e))
        ok = False
    else:
        print('%-22s %s' % (nm, 'OK' if ok else 'FAIL'))
    results.append((nm, ok))

passed = sum(1 for _, ok in results if ok)
print('TOTAL: %d/%d %s' % (passed, len(results),
                           'ALL PASS' if passed == len(results) else 'FAILURES'))
sys.exit(0 if passed == len(results) else 1)