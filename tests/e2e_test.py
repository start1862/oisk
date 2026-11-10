#!/usr/bin/env python3
"""End-to-end pipeline regression: preprocess -> tokenize -> parse -> codegen
-> simulate.  This is the first OSCC test that goes through preproc, proving
the #include/#define/#if chain feeds the real compiler (not just preproc in
isolation).
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, '/opt/oisk')
from oscc import tokenize, Parser, CodeGen
from osma import Asm
from sim import Sim
from preproc import preprocess

results = []


def run_c(src, checks, include_paths=None, cur_file='<input>',
          max_steps=300000):
    pp = preprocess(src, cur_file, include_paths or ['.'])
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
        print('  %-4s got=%-8d want=%-8d %s' % (nm, got, want,
                                                'OK' if good else 'FAIL'))
    print('  steps=%d halted=%s -> %s' % (steps, s.halted, 'OK' if ok else 'FAIL'))
    return ok


HEADER = '''\
#ifndef _FLAGS_H
#define _FLAGS_H
#define BASE 100
#define WRAP(n) (BASE + (n))
#define SCALE_ARRAY 2
typedef struct { int a; int b; } Pair;
#endif
'''

MAIN = '''\
#include "flags.h"
Pair arr[3];
int g;
int h;
int main()
{
    arr[0].a = WRAP(1);
    arr[0].b = 2;
    arr[1].a = 30;
    arr[1].b = 40;
#if BASE == 100
    g = arr[0].a + arr[1].b;
#else
    g = 0;
#endif
#ifdef SCALE_ARRAY
    h = arr[0].a * SCALE_ARRAY;
#endif
    return 0;
}
'''

tmpdir = tempfile.mkdtemp(prefix='oscc_e2e_')
try:
    with open(os.path.join(tmpdir, 'flags.h'), 'w') as f:
        f.write(HEADER)
    print('[e2e_include_macro_struct]')
    results.append(('e2e_include_macro_struct',
                    run_c(MAIN, [('g', 141), ('h', 202)],
                          include_paths=[tmpdir],
                          cur_file=os.path.join(tmpdir, 'main.c'))))

    # conditional compilation selecting the OTHER branch
    src2 = '''\
#define LEVEL 0
int g;
int main()
{
#if LEVEL == 1
    g = 111;
#elif LEVEL == 0
    g = 222;
#else
    g = 333;
#endif
    return 0;
}
'''
    print('[e2e_if_elif_else]')
    results.append(('e2e_if_elif_else', run_c(src2, [('g', 222)])))

    # function-like macro with token paste used to build an identifier that
    # is then used as a variable (paste must happen before parsing)
    src3 = '''\
#define DECL(n) int v ## n
#define SET(n, val) v ## n = val
DECL(1);
DECL(2);
int g;
int main()
{
    SET(1, 7);
    SET(2, 5);
    g = v1 * v2;
    return 0;
}
'''
    print('[e2e_token_paste_vars]')
    results.append(('e2e_token_paste_vars', run_c(src3, [('g', 35)])))
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

passed = sum(1 for _, ok in results if ok)
total = len(results)
print('TOTAL: %d/%d %s' % (passed, total,
                           'ALL PASS' if passed == total else 'FAILURES'))
sys.exit(0 if passed == total else 1)