#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""build_iso.py - package the oisk ko system as a bootable ISO 9660 image.

Design
------
The OISC machine has no BIOS and its kernel's DISK device reads 512-byte
sectors (GPU cmd 14: op = lba | (nsec<<16) | (dir<<24)).  A real ISO 9660
image uses 2048-byte logical blocks, so the two layouts are *not* directly
compatible.  We exploit the one region of an ISO that is free-form:

  ISO System Area = bytes 0 .. 32767 (16 * 2048)
                    (reserved by ISO 9660, never part of the filesystem)

oisk_hd.bin is exactly 32768 bytes (64 * 512), so we place a verbatim copy
of the OISC boot disk into the System Area.  When the virtual machine boots
oisk_core.bin as firmware and uses oisk.iso as its DISK device, the ko
kernel's DISK reads hit LBA0.. of the System Area exactly as they did with
the raw .bin -- the ISO boots unchanged.  Meanwhile the region from ISO LBA
16 upward is a fully standards-compliant ISO 9660 filesystem containing the
same payloads as browsable files:

  /OISK/BOOT.BIN    core BIOS firmware image
  /OISK/ELFLDR.KO   elfloader.ko kernel module
  /OISK/INIT.ELF    userland ELF image

El Torito: a Boot Record Volume Descriptor + boot catalog mark the image as
bootable media; the boot entry points at the System Area (the OISC boot
disk) with sector count 64 (64 * 512 B).

Layout (2048-byte LBAs)
  LBA  0..15   System Area = oisk_hd.bin (OISC boot disk)      [0..32767]
  LBA 16       Primary Volume Descriptor                        PVD
  LBA 17       Boot Record Volume Descriptor (El Torito)        BVD
  LBA 18       Volume Descriptor Set Terminator
  LBA 19       Path Table (L)
  LBA 20       Path Table (M)
  LBA 21       Root directory extent
  LBA 22       El Torito boot catalog
  LBA 23..     file extents (BOOT.BIN, ELFLDR.KO, INIT.ELF)
  LBA ..       /OISK directory extent
"""
import os
import struct
import sys

SECTOR = 2048                # ISO 9660 logical block size (bytes)
DISC_SECTOR = 512            # OISC DISK device sector size
SYSTEM_AREA = 16 * SECTOR    # bytes 0..32767: free-form region

LBA_PVD = 16
LBA_BVD = 17
LBA_TERM = 18
LBA_PTL = 19
LBA_PTM = 20
LBA_ROOT = 21
LBA_CAT = 22
LBA_FIRST_FILE = 24          # one spare LBA after the catalog


def both32(v):
    return struct.pack('<I', v) + struct.pack('>I', v)


def both16(v):
    return struct.pack('<H', v) + struct.pack('>H', v)


def dtime7():
    """7-byte directory record timestamp."""
    return bytes([124, 1, 13, 12, 0, 0, 0])


def dtime17():
    """17-byte volume descriptor timestamp 'YYYYMMDDHHMMSScc' + NUL."""
    return b'2026011312000000' + b'\x00'


def ident(s, n):
    b = s.encode('ascii')
    if len(b) > n:
        b = b[:n]
    return b + b' ' * (n - len(b))


def dirrec(name_bytes, extent_lba, length, is_dir):
    """One ISO 9660 directory record (length strictly 33+name_len+pad)."""
    name_len = len(name_bytes)
    pad = 1 if (name_len % 2 == 0) else 0
    r = bytearray()
    r.append(33 + name_len + pad)          # record length
    r.append(0)                            # extended attribute length
    r += both32(extent_lba)                # extent (LBA + LBA)
    r += both32(length)                    # data length (LE + BE)
    r += dtime7()                          # recording date 7 bytes
    r.append(0x02 if is_dir else 0x00)     # file flags
    r.append(0)                            # file unit size
    r.append(0)                            # interleave gap
    r += both16(1)                         # volume sequence number
    r.append(name_len)                     # name length
    r += name_bytes                        # name
    if pad:
        r.append(0)                        # padding (even name len)
    return bytes(r)


def iso_name(path):
    """'OISK/FOO.BAR' -> b'FOO.BAR;1' (ISO 8.3, level 1)."""
    base = path.rsplit('/', 1)[-1]
    stem, _, ext = base.partition('.')
    stem = (stem.upper()[:8]).ljust(8, '_')
    ext = (ext.upper()[:3]).ljust(3, '_')
    return ('%s.%s;1' % (stem, ext)).encode('ascii')


def build_iso(hd, files):
    """hd: 32768-byte OISC boot disk; files: [(iso_path, data)]."""
    if len(hd) != SYSTEM_AREA:
        raise ValueError('boot disk must be %d B, got %d'
                         % (SYSTEM_AREA, len(hd)))

    extents = {}
    next_lba = LBA_FIRST_FILE
    for path, data in files:
        nsec = max(1, (len(data) + SECTOR - 1) // SECTOR)
        extents[path] = (next_lba, len(data))
        next_lba += nsec

    oisk_lba = next_lba
    next_lba += 1
    total_lba = next_lba
    img = bytearray(total_lba * SECTOR)

    # System Area: verbatim OISC boot disk
    img[0:SYSTEM_AREA] = hd

    # file data
    for path, data in files:
        lba, ln = extents[path]
        img[lba * SECTOR:lba * SECTOR + ln] = data

    # root directory
    root_dir = (dirrec(b'\x00', LBA_ROOT, SECTOR, True)
                + dirrec(b'\x01', LBA_ROOT, SECTOR, True)
                + dirrec(b'OISK', oisk_lba, SECTOR, True))
    img[LBA_ROOT * SECTOR:(LBA_ROOT + 1) * SECTOR] = \
        root_dir.ljust(SECTOR, b'\0')

    # /OISK directory
    oisk_dir = (dirrec(b'\x00', oisk_lba, SECTOR, True)
                + dirrec(b'\x01', LBA_ROOT, SECTOR, True))
    for path, data in files:
        lba, ln = extents[path]
        oisk_dir += dirrec(iso_name(path), lba, ln, False)
    img[oisk_lba * SECTOR:(oisk_lba + 1) * SECTOR] = \
        oisk_dir.ljust(SECTOR, b'\0')

    # path tables: entry = len_di, ext_attr, extent(4), parent(2), name, pad
    def pt(root_ext, oisk_ext, e):
        out = bytearray()
        out.append(1); out.append(0)
        out += struct.pack(e + 'I', root_ext)
        out += struct.pack(e + 'H', 1)
        out += b'\x00\x00'
        out.append(4); out.append(0)
        out += struct.pack(e + 'I', oisk_ext)
        out += struct.pack(e + 'H', 1)
        out += b'OISK'
        return bytes(out)

    pt_l = pt(LBA_ROOT, oisk_lba, '<')
    pt_m = pt(LBA_ROOT, oisk_lba, '>')
    img[LBA_PTL * SECTOR:LBA_PTL * SECTOR + len(pt_l)] = pt_l
    img[LBA_PTM * SECTOR:LBA_PTM * SECTOR + len(pt_m)] = pt_m

    # PVD
    pvd = bytearray(SECTOR)
    pvd[0] = 0x01
    pvd[1:6] = b'CD001'
    pvd[6] = 0x01
    pvd[8:40] = ident('', 32)
    pvd[40:72] = ident('OISK', 32)
    pvd[80:88] = both32(total_lba)
    pvd[120:124] = both16(1)
    pvd[124:128] = both16(1)
    pvd[128:132] = both16(SECTOR)
    pvd[132:140] = both32(len(pt_l))
    pvd[140:144] = struct.pack('<I', LBA_PTL)
    pvd[144:148] = struct.pack('<I', 0)
    pvd[148:152] = struct.pack('>I', LBA_PTM)
    pvd[152:156] = struct.pack('>I', 0)
    rr = dirrec(b'\x00', LBA_ROOT, SECTOR, True)
    pvd[156:156 + len(rr)] = rr
    pvd[190:318] = ident('', 128)
    pvd[318:446] = ident('', 128)
    pvd[446:574] = ident('', 128)
    pvd[574:702] = ident('OISK', 128)
    pvd[813:830] = dtime17()
    pvd[830:847] = dtime17()
    pvd[847:864] = b'0' * 16 + b'\x00'
    pvd[864:881] = b'0' * 16 + b'\x00'
    pvd[881] = 0x01
    pvd[882] = 0x01
    img[LBA_PVD * SECTOR:(LBA_PVD + 1) * SECTOR] = pvd

    # Boot Record Volume Descriptor (El Torito)
    bvd = bytearray(SECTOR)
    bvd[0] = 0x00
    bvd[1:6] = b'CD001'
    bvd[6] = 0x01
    bvd[7:39] = ident('EL TORITO SPECIFICATION', 32)
    bvd[71:75] = struct.pack('<I', LBA_CAT)
    img[LBA_BVD * SECTOR:(LBA_BVD + 1) * SECTOR] = bvd

    # terminator
    term = bytearray(SECTOR)
    term[0] = 0xFF
    term[1:6] = b'CD001'
    term[6] = 0x01
    img[LBA_TERM * SECTOR:(LBA_TERM + 1) * SECTOR] = term

    # El Torito boot catalog
    val = bytearray(32)
    val[0] = 0x01
    val[1] = 0x00
    val[4:28] = b'OISK BOOT CATALOG'.ljust(24, b' ')
    val[30:32] = b'\x55\xaa'
    cks = 0
    for i in range(0, 32, 2):
        cks = (cks + struct.unpack('<H', bytes(val[i:i + 2]))[0]) & 0xFFFF
    val[28:30] = struct.pack('<H', (0x10000 - cks) & 0xFFFF)
    ent = bytearray(32)
    ent[0] = 0x88
    ent[1] = 0x00
    ent[6:8] = struct.pack('<H', 64)     # 64 sectors * 512 B = System Area
    ent[8:12] = struct.pack('<I', 0)     # boot image LBA 0 (System Area)
    img[LBA_CAT * SECTOR:(LBA_CAT + 1) * SECTOR] = \
        (bytes(val) + bytes(ent)).ljust(SECTOR, b'\0')

    return bytes(img)


def parse_recs(buf):
    """Parse ISO directory records; returns [(name, extent_lba, size, flags)]."""
    recs = []
    i = 0
    while i < len(buf):
        rl = buf[i]
        if rl == 0 or i + rl > len(buf):
            break
        extent = struct.unpack('<I', buf[i + 2:i + 6])[0]
        size = struct.unpack('<I', buf[i + 10:i + 14])[0]
        flags = buf[i + 25]
        nl = buf[i + 32]
        name = bytes(buf[i + 33:i + 33 + nl])
        recs.append((name, extent, size, flags))
        i += rl
    return recs


def validate(iso, expect_files):
    res = []

    def chk(name, cond):
        res.append((name, bool(cond)))

    def blk(i):
        return iso[i * SECTOR:(i + 1) * SECTOR]

    chk('PVD 01CD001', blk(LBA_PVD)[:6] == b'\x01CD001')
    chk('BVD 00CD001', blk(LBA_BVD)[:6] == b'\x00CD001')
    chk('TERM FFCD001', blk(LBA_TERM)[:6] == b'\xffCD001')
    chk('El Torito string', blk(LBA_BVD)[7:39].rstrip(b' ') == b'EL TORITO SPECIFICATION')
    cat = blk(LBA_CAT)
    chk('boot catalog 55AA', cat[30:32] == b'\x55\xaa')
    chk('boot catalog header 01', cat[0] == 0x01)
    chk('boot catalog checksum 0',
        (sum(struct.unpack('<16H', cat[0:32])) & 0xFFFF) == 0)
    chk('boot entry 88', cat[32] == 0x88)
    # System Area must be the boot disk verbatim
    chk('SystemArea init.elf EF', iso[12 * 512:12 * 512 + 4] == b'\x7fELF')
    chk('SystemArea non-empty', any(iso[0:SYSTEM_AREA]))
    # root dir
    root = parse_recs(blk(LBA_ROOT))
    names = [n for n, _, _, _ in root]
    chk('root has . .. OISK', names[0] == b'\x00' and names[1] == b'\x01'
        and b'OISK' in names)
    oisk = [r for r in root if r[0] == b'OISK']
    if oisk:
        oisk_lba = oisk[0][1]
        sub = parse_recs(iso[oisk_lba * SECTOR:oisk_lba * SECTOR + SECTOR])
        subnames = [n.upper().split(b';')[0] for n, _, _, _ in sub]
        for want in expect_files:
            wb = iso_name('OISK/' + want).upper().split(b';')[0]
            chk('/OISK/%s present' % want, wb in subnames)
        # file extents must hold the real payloads
        for name, extent, size, flags in sub:
            if flags & 2:
                continue
            if name.upper().startswith(b'INIT'):
                chk('INIT.ELF extent is ELF',
                    iso[extent * SECTOR:extent * SECTOR + 4] == b'\x7fELF')
    bad = [n for n, c in res if not c]
    for n, c in res:
        print('  %s %s' % ('ok  ' if c else 'FAIL', n))
    print('ISO validate: %d/%d ok' % (len(res) - len(bad), len(res)))
    return not bad


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, 'out')
    hd = open(os.path.join(out, 'oisk_hd.bin'), 'rb').read()
    core = open(os.path.join(out, 'oisk_core.bin'), 'rb').read()
    ko_len = 12 * 512
    ko = hd[0:ko_len]
    elf = hd[ko_len:]

    iso = build_iso(hd, [
        ('OISK/BOOT.BIN', core),
        ('OISK/ELFLDR.KO', ko),
        ('OISK/INIT.ELF', elf),
    ])
    path = os.path.join(out, 'oisk.iso')
    open(path, 'wb').write(iso)
    ok = validate(iso, ['BOOT.BIN', 'ELFLDR.KO', 'INIT.ELF'])
    print('iso: %s (%d B, %d x %d B) %s'
          % (path, len(iso), len(iso) // SECTOR, SECTOR,
             'VALID' if ok else 'INVALID'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())