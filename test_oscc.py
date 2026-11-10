#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""test_oscc.py - compile C with oscc, run in Sim, assert global values.

Usage: python3 test_oscc.py <file.c> [global_name expected ...]
If globs given, checks mem value of that global after run.
Prints steps/halted/pc and dump of requested globals.
"""
import struct
import sys
sys.path.insert(0, '/opt/oisk')

from oscc import tokenize, Parser, CodeGen
from osma import Asm
from sim import Sim


def compile_cg(src):
    toks = tokenize(src)
    p = Parser(toks)
    decls = p.parse()
    cg = CodeGen(Asm())
    cg.compile(decls)
    words = cg.build()
    return cg, words


def main():
    path = sys.argv[1]
    src = open(path).read()
    cg, words = compile_cg(src)
    # dump words
    print('compiled: %d words (%d B)' % (len(words), len(words) * 4))
    # list globals
    for name, g in cg.globals.items():
        print('  global %-12s array=%s sym=%r' % (name, g['array'], g['sym']))

    s = Sim()
    s.load_words(words)
    n = s.run()
    print('sim: %d steps halted=%s pc=0x%x' % (n, s.halted, s.pc))

    # check globals by positional args: name expected...
    args = sys.argv[2:]
    ok = True
    for i in range(0, len(args), 2):
        name = args[i]
        want = int(args[i + 1], 0)
        g = cg.globals[name]
        sym = g['sym']
        # sym is G('__g_name'); its word address = globs value[1]
        addr = cg.a.globs[sym.name][1]
        got = s.mem[addr]
        good = (got & 0xffffffff) == (want & 0xffffffff)
        ok = ok and good
        print('  global %s @0x%x = 0x%08x want 0x%x %s'
              % (name, addr, got, want & 0xffffffff,
                 'OK' if good else 'FAIL'))
    print('RESULT:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())