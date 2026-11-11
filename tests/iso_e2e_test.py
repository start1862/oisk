#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""End-to-end test for the oisk ISO image.

Builds oisk.iso from the ko build outputs (oisk_core.bin firmware +
oisk_hd.bin boot disk), verifies:
  1. ISO 9660 structure is valid (PVD/BVD/Terminator, path tables,
     root and /OISK directory records, El Torito boot catalog)
  2. every /OISK file's full content matches the corresponding region
     of the OISC boot disk (cross-sector read)
  3. the whole ko chain BOOTS from the ISO used as the DISK device:
     core BIOS -> elfloader.ko kernel -> init.elf userland, all
     8 serial tokens in order.
"""
import os
import struct
import sys
sys.path.insert(0, '/opt/oisk')
sys.path.insert(0, '/opt/oisk/ko')
from sim import Sim
import build_iso

KO = '/opt/oisk/ko'
OUT = os.path.join(KO, 'out')
S = build_iso.SECTOR
KO_LEN = 12 * 512        # 12 sectors * 512 B elfloader.ko on boot disk

NEED = [
    'oisk: core boot',
    'loading elfloader.ko from disk',
    'ko loaded, jumping to elfloader',
    'oisk: elfloader.ko',
    'init.elf: magic ok',
    'init.elf: PT_LOAD segments loaded, jumping to e_entry',
    'hello from user space via kernel puts!',
    'ko ABI: jump_dyn trampoline works.',
]


def walk(buf):
    """Parse ISO directory records -> [(name, extent_lba, size, flags)]."""
    recs = []
    i = 0
    while i < len(buf):
        rl = buf[i]
        if rl == 0 or i + rl > len(buf):
            break
        ext = struct.unpack('<I', buf[i + 2:i + 6])[0]
        size = struct.unpack('<I', buf[i + 10:i + 14])[0]
        flags = buf[i + 25]
        nl = buf[i + 32]
        recs.append((bytes(buf[i + 33:i + 33 + nl]), ext, size, flags))
        i += rl
    return recs


def read_iso(data, lba, size):
    """Read a file extent spanning multiple 2048-byte logical blocks."""
    out = bytearray()
    while len(out) < size:
        sec = lba + len(out) // S
        out += data[sec * S:sec * S + S]
    return bytes(out[:size])


def main():
    # ---- 1. build the ISO from current ko outputs ----
    core = open(os.path.join(OUT, 'oisk_core.bin'), 'rb').read()
    hd = open(os.path.join(OUT, 'oisk_hd.bin'), 'rb').read()
    iso = build_iso.build_iso(hd, [
        ('OISK/BOOT.BIN', core),
        ('OISK/ELFLDR.KO', hd[:KO_LEN]),
        ('OISK/INIT.ELF', hd[KO_LEN:]),
    ])
    assert len(hd) == build_iso.SYSTEM_AREA, 'boot disk size'

    # ---- 2. ISO structure checks ----
    def sect(i):
        return iso[i * S:(i + 1) * S]
    pvd, bvd, term = sect(16), sect(17), sect(18)
    assert pvd[:6] == b'\x01CD001'
    assert bvd[:6] == b'\x00CD001'
    assert term[:6] == b'\xffCD001'
    assert bvd[7:39].rstrip(b' ') == b'EL TORITO SPECIFICATION'
    assert iso[build_iso.LBA_CAT * S + 30:build_iso.LBA_CAT * S + 32] == b'\x55\xaa'
    # root / OISK dirs
    root = walk(sect(21))
    names = [n for n, _, _, _ in root]
    assert b'\x00' in names and b'\x01' in names and b'OISK' in names
    oisk_lba = [r[1] for r in root if r[0] == b'OISK'][0]
    sub = walk(sect(oisk_lba))
    want = {b'BOOT____.BIN;1', b'ELFLDR__.KO_;1', b'INIT____.ELF;1'}
    got = {n for n, _, _, _ in sub}
    assert want <= got, 'missing files: %r' % (want - got)

    # ---- 3. full content verify (cross-sector) ----
    for nm, ext, size, flags in sub:
        if flags & 2 or size == 0:
            continue
        frag = read_iso(iso, ext, size)
        if nm.upper().startswith(b'BOOT'):
            assert frag == core, 'BOOT.BIN mismatch'
        elif nm.upper().startswith(b'ELFLDR'):
            assert frag == hd[:KO_LEN], 'ELFLDR.KO mismatch'
        elif nm.upper().startswith(b'INIT'):
            assert frag == hd[KO_LEN:KO_LEN + size], 'INIT.ELF mismatch'
            assert frag[:4] == b'\x7fELF', 'init not ELF'
    print('ISO structure + content: OK')

    # ---- 4. boot the whole chain from the ISO (DISK device) ----
    s = Sim()
    s.load_bin(os.path.join(OUT, 'oisk_core.bin'))
    s.load_disk_iso(iso)          # register ISO bytes as the disk
    s.run(max_steps=4000000)
    out = bytes(s.out).decode(errors='replace')
    pos = 0
    for tok in NEED:
        i = out.find(tok, pos)
        if i < 0:
            print('FAIL: missing token %r' % tok)
            return 1
        pos = i + len(tok)
    print('ISO BOOT CHAIN OK: %d/%d tokens in order' % (len(NEED), len(NEED)))
    return 0


if __name__ == '__main__':
    sys.exit(main())