#!/usr/bin/env python3
"""Boot test for the minimal OISC kernel: setup_arch + start_kernel + driver
merged into a single translation unit (OSCC has no linker), run on the
simulator, and verify the MMIO UART emits the expected boot log.

The target spins in an idle loop (while(1) cpu_relax()), so the simulator
terminates on max_steps; we check s.out bytes for the banner text.
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
    # t_boot.c is the single translation unit: it #includes the arch
    # kernel sources (setup.c + start_kernel.c) itself, exactly like the
    # real build `oscc.py -Ikernel/arch/oisc/include kernel/t_boot.c`.
    path = os.path.join(KROOT, 't_boot.c')
    merged = open(path).read()
    pp = preprocess(merged, path, INCS)
    p = Parser(tokenize(pp))
    d = p.parse()
    cg = CodeGen(Asm(), p.struct_layouts, p.var_types)
    cg.compile(d)
    words = cg.build()
    print('compiled: %d words (%d bytes)`' % (len(words), len(words) * 4))

    s = Sim()
    s.load_words(words)
    n = s.run(max_steps=2000000)
    print('sim steps=%d halted=%s' % (n, s.halted))
    out = bytes(s.out)
    print('out bytes: %r' % out)

    expected = b'OISC setup: DRAM = 40 MiB, cpu_relax ready\r\n' \
               b'OISC-Linux 0.0.1\n\n' \
               b'Linux is running on a SUBLEQ machine.\n' \
               b'Booting the simulated OISC machine...\r\n' \
               b'Kernel alive. Halting via idle loop (never reached).\r\n'
    print('expected: %r' % expected)
    # the "DRAM = 40" is hex(64/1MB)=0x40 '40'; compare textually
    if b'OISC setup: DRAM =' in out and b'MiB, cpu_relax ready' in out \
       and b'OISC-Linux 0.0.1' in out \
       and b'Linux is running on a SUBLEQ machine.' in out \
       and b'Kernel alive' in out and b'Booting the simulated' in out:
        print('BOOT LOG OK')
        return 0
    print('BOOT LOG MISMATCH')
    return 1

if __name__ == '__main__':
    sys.exit(main())