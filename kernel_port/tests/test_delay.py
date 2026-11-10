#!/usr/bin/env python3
"""Regression test: kernel_port/lib/delay.c compiles and runs on OISC.

This is the first REAL kernel source file ported to the OISC architecture.
It exercises the whole toolchain against kernel-style C:
  - <asm/...> and <linux/...> include resolution through the port's header tree
  - EXPORT_SYMBOL() annotation macros expanding to nothing (leaving a lone ';')
  - C integer suffixes (0x10C7UL / 100UL) in the tokeniser
  - 32-bit-only arithmetic: no long long, no 64-bit shift
  - pointer write (*p = ...) used by read_current_timer()

Checks performed:
  1. every public delay entry point can be called and returns (no hang)
  2. read_current_timer() writes the counter value through a pointer
  3. __delay(0) is a no-op and __delay(n) terminates
"""
import sys

sys.path.insert(0, '/opt/oisk')
from oscc import tokenize, Parser, CodeGen
from preproc import preprocess
from osma import Asm
from sim import Sim

INCLUDE_PATHS = ['/opt/oisk/kernel_port',
                 '/opt/oisk/kernel_port/include',
                 '/opt/oisk', '.']

CYCLE_VALUE = 4          # what the fake oisc_get_cycles() returns


class Src:
    """A test program: stubs + the real delay.c + a main() driver."""

    PRELUDE = '''
#include <asm/processor.h>
#include <linux/types.h>

unsigned long loops_per_jiffy;

unsigned long oisc_get_cycles(void){ return %d; }
void cpu_relax(void){ }

unsigned long ran_delay;
unsigned long ran_udelay;
unsigned long ran_ndelay;
unsigned long ran_constud;
unsigned long timer_val;
unsigned long delay_ret;
''' % CYCLE_VALUE

    DELAY_C = '#include "/opt/oisk/kernel_port/lib/delay.c"\n'

    MAIN = '''
int main(void){
    unsigned long t;
    ram_dummy = 0;
    __delay(0);
    ran_delay = 1;
    __udelay(1);
    ran_udelay = 1;
    __ndelay(1);
    ran_ndelay = 1;
    __const_udelay(1);
    ran_constud = 1;
    delay_ret = read_current_timer(&t);
    timer_val = t;
    return 0;
}
'''


def build(src):
    pre = preprocess(src, '/opt/oisk/kernel_port/tests/test_delay.c',
                     INCLUDE_PATHS)
    p = Parser(tokenize(pre))
    decls = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(decls)
    words = cg.build()
    s = Sim()
    s.load_words(words)
    steps = s.run(max_steps=3000000)
    return cg, s, steps


def signed(v):
    return v - 2 ** 32 if v >= 2 ** 31 else v


def get(cg, s, name):
    return signed(s.mem[cg.a.globs['__g_' + name][1]])


results = []


def case(name, fn):
    try:
        ok = fn()
    except Exception as e:
        print('%-24s EXC %s: %s' % (name, type(e).__name__, e))
        ok = False
    else:
        print('%-24s %s' % (name, 'OK' if ok else 'FAIL'))
    results.append((name, ok))


def t_all_entry_points():
    """Every public delay function is callable and the program halts."""
    src = Src.PRELUDE + '''
unsigned long ram_dummy;
''' + Src.DELAY_C + Src.MAIN
    cg, s, steps = build(src)
    if not s.halted:
        print('    did not halt')
        return False
    checks = [('ran_delay', 1), ('ran_udelay', 1),
              ('ran_ndelay', 1), ('ran_constud', 1)]
    ok = True
    for nm, want in checks:
        got = get(cg, s, nm)
        if got != want:
            print('    %s = %d, want %d' % (nm, got, want))
            ok = False
    return ok


def t_read_current_timer():
    """read_current_timer() stores the counter through a pointer and returns 0."""
    src = Src.PRELUDE + '''
unsigned long ram_dummy;
''' + Src.DELAY_C + Src.MAIN
    cg, s, steps = build(src)
    ok = True
    tv = get(cg, s, 'timer_val')
    if tv != CYCLE_VALUE:
        print('    timer_val = %d, want %d' % (tv, CYCLE_VALUE))
        ok = False
    ret = get(cg, s, 'delay_ret')
    if ret != 0:
        print('    read_current_timer returned %d, want 0' % ret)
        ok = False
    return ok


def t_delay_zero_noop():
    """__delay(0) must not spin (program still halts quickly)."""
    src = Src.PRELUDE + '''
unsigned long ram_dummy;
''' + Src.DELAY_C + '''
int main(void){
    __delay(0);
    ran_delay = 1;
    return 0;
}
'''
    cg, s, steps = build(src)
    ok = s.halted and get(cg, s, 'ran_delay') == 1
    if not ok:
        print('    halted=%s steps=%d ran=%d'
              % (s.halted, steps, get(cg, s, 'ran_delay')))
    return ok


case('all_entry_points', t_all_entry_points)
case('read_current_timer', t_read_current_timer)
case('delay_zero_noop', t_delay_zero_noop)

passed = sum(1 for _, ok in results if ok)
print('TOTAL: %d/%d %s' % (passed, len(results),
                           'ALL PASS' if passed == len(results) else 'FAILURES'))
sys.exit(0 if passed == len(results) else 1)