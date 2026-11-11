#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""End-to-end test of the ko mechanism: core -> elfloader.ko -> init.elf.

Loads ko/out/oisk_core.bin as firmware and ko/out/oisk_hd.bin as the
virtual disk into Sim (which now emulates the DISK MMIO command, GPU
cmd 14), runs, and checks the serial output sequence proves the whole
three-stage boot chain worked.
"""
import os
import sys

sys.path.insert(0, '/opt/oisk')
from sim import Sim

KO = '/opt/oisk/ko'
CORE = os.path.join(KO, 'out', 'oisk_core.bin')
DISK = os.path.join(KO, 'out', 'oisk_hd.bin')


def main():
    s = Sim()
    n = s.load_bin(CORE)
    s.load_disk(DISK)
    steps = s.run(max_steps=4000000)
    out = bytes(s.out).decode(errors='replace')
    print('--- serial output ---')
    print(out)
    print('--- steps=%d halted=%s pc=%x ---' % (steps, s.halted, s.pc))
    # the whole chain must print all stages in order:
#   core BIOS -> ko kernel -> userland via jump_dyn trampoline
    need = [
        'oisk: core boot',
        'loading elfloader.ko from disk',
        'ko loaded, jumping to elfloader',
        'oisk: elfloader.ko',
        'init.elf: magic ok',
        'init.elf: PT_LOAD segments loaded, jumping to e_entry',
        'hello from user space via kernel puts!',
        'ko ABI: jump_dyn trampoline works.',
    ]
    pos = 0
    for token in need:
        i = out.find(token, pos)
        if i < 0:
            print('FAIL: missing token %r' % token)
            return 1
        pos = i + len(token)
    print('KO CHAIN OK: %d/%d tokens in order' % (len(need), len(need)))
    return 0


if __name__ == '__main__':
    sys.exit(main())