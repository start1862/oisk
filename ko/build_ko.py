#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""oisk ko mechanism - core BIOS + elfloader.ko kernel + init userland.

The ko mechanism (validated in the OISKOS work) is the heart of this OS:

  1. core (BIOS, linked at word 0) prints a banner, issues the QEMU DISK
     MMIO command (GPU cmd 14) to copy elfloader.ko off the virtual disk
     into guest RAM at word LOAD_WORD, then jumps into it.
  2. elfloader.ko is the kernel: it issues DISK to load init.elf (a flat
     32-bit ELF) to ELF_BASE, then jumps to INIT_BASE (after the 21-word
     ELF header).  It also provides kernel services to userland:
       srv_puts : print a NUL-terminated string (pointer in k_A0)
       srv_exit : halt the machine
  3. init.elf is userland.  It calls kernel services through the ko ABI:
     - arguments  in  k_A0 / k_A1  (fixed global words at 0x20000/0x20004)
     - return addr in  k_RET  stored NEGATED ( -retaddr )
     - calls go through a GLOBAL SHARED jump_dyn self-modifying
       trampoline cell: its C field word ("dynC", tpl_cell+2) holds the
       *next target* (stored NEGATED as the A operand of subleq Z,Z,dynC).
       A call site is:
          clear dynC                      (subleq dynC,dynC)
          dynC = -local patch entry       (subleq -patch,dynC)
          jump trampoline                 (subleq Z,Z,tpl)
       the patch code then:
          k_A0 = str ; k_RET = -retaddr
          dynC = -kernel service          (subleq -srv,dynC)
          jump trampoline                 -> service runs
       the service returns by:
          dynC = 0 - k_RET = retaddr      (subleq k_RET,dynC)
          jump trampoline                 -> back to the call site
  4. Two-pass linking: pass 1 assembles the kernel and records absolute
     addresses of its services/trampoline; pass 2 assembles init.elf with
     those injected as externs (K_SRV_PUTS/K_TPL/K_DYN/K_EXIT), exactly
     the way OISKOS resolved inter-module symbols at build time.

Everything is assembled with the in-repo osma.py so the whole toolchain
stays self-hosted (oscc/osma/sim).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from osma import Asm, L, C, G, write_words  # noqa: E402

# ---- layout constants (word addresses) ----
LOAD_WORD = 0x100000      # core: where DISK copies elfloader.ko
ELF_BASE = 0x400000       # elfloader: where DISK stages init.elf image
INIT_BASE = 0x500000      # elfloader: PT_LOAD p_paddr / entry of init.elf
KO_SECTORS = 12            # elfloader.ko occupies LBA0-11 (6144B max)
INIT_SECTORS = 16          # init.elf may use up to 16 sectors (8192B)

# ko ABI fixed global words
K_A0 = 0x20000
K_A1 = 0x20004
K_RET = 0x20008

# ELF constants (WORD-addressed on OISC: DISK converts every 4 ELF bytes
# into one 32-bit memory word)
#   ELF header word layout:
#     word  0        = e_ident[0..3]  = magic 0x464c457f
#     word  4..5     = e_type/e_machine/e_version (ignored)
#     word  6        = e_entry            (word address)
#     word  7        = e_phoff            (WORD offset of phdr table)
#     word 11 low16  = e_phnum
#   program header (8 words each):
#     +0 p_type, +1 p_offset(word), +2 p_vaddr(word),
#     +3 p_paddr(word), +4 p_filesz(words), +5 p_memsz, +6/+7 ignore
ELF_MAGIC_VAL = 0x464c457f   # "\x7fELF" little-endian
PHDR_WORDS = 8               # words per program header
ELF_HDR_WORDS = 13           # ELF header = 52 bytes = 13 words


def load_word(a, slot, addr):
    """slot = -mem[addr]  (negated word load from a CONSTANT word address)."""
    a.sq(a.slot(slot), a.slot(slot))                    # slot = 0
    a.sq(a.fixed('LW_%d' % addr, addr), a.slot(slot))   # slot = -mem[addr]


def load_rel(a, slot, word_off):
    """slot = -mem[+phcur + word_off] using the current 'phcur' slot value
    (phcur holds NEGATED word address).  Patch the loader cell's A field
    with the positive address (0 - phcur [+ word_off]) and read through it."""
    a.sq(a.slot(slot), a.slot(slot))                    # slot = 0
    # patch ldr cell A := +phcur  (0 - mem[phcur])
    a.sq(a.field_addr(L('ldr_%s' % slot), 0),
         a.field_addr(L('ldr_%s' % slot), 0))           # A = 0
    a.sq(a.slot('phcur'), a.field_addr(L('ldr_%s' % slot), 0))  # A = +phcur
    # A += word_off  (A holds a positive word address; add in small steps)
    for _ in range(word_off):
        a.sq(a.const(-1), a.field_addr(L('ldr_%s' % slot), 0))
    a.label('ldr_%s' % slot)
    a.sq(a.field_addr(L('ldr_%s' % slot), 0), a.slot(slot),
         a.field_addr(L('ldr_after_%s' % slot)))        # slot = -mem[A]
    a.label('ldr_after_%s' % slot)


def set_ptr(a, cell_name, slot_neg):
    """Patch `cell_name`'s A field := +ptr, where `slot_neg` holds -ptr."""
    a.sq(a.field_addr(L(cell_name), 0), a.field_addr(L(cell_name), 0))  # A = 0
    a.sq(a.slot(slot_neg), a.field_addr(L(cell_name), 0))               # A = +ptr


def set_ptrb(a, cell_name, slot_neg):
    """Patch `cell_name`'s B field := +ptr, where `slot_neg` holds -ptr."""
    a.sq(a.field_addr(L(cell_name), 1), a.field_addr(L(cell_name), 1))  # B = 0
    a.sq(a.slot(slot_neg), a.field_addr(L(cell_name), 1))               # B = +ptr


_bz_counter = [0]


def branch_zero(a, vslot, target):
    """Emit: if mem[vslot] == 0 goto target, else fall through.
    Uses the two-sided test (v<=0 then v>=0) since subleq only gives the
    signed <= 0 primitive.  Clobbers only a scratch slot 'w'."""
    _bz_counter[0] += 1
    i = _bz_counter[0]
    le = 'bz_le_%d' % i
    nz = 'bz_nz_%d' % i
    # if v <= 0 -> le ; else (v > 0) definitely nonzero
    a.sq(a.const(0), a.slot(vslot), a.field_addr(L(le)))
    a.sq(a.const(0), a.const(0), a.field_addr(L(nz)))
    a.label(le)                                   # here v <= 0
    a.sq(a.slot('w'), a.slot('w'))                # w = 0
    a.sq(a.slot(vslot), a.slot('w'))              # w = -v
    a.sq(a.const(0), a.slot('w'), a.field_addr(L(target)))  # v >= 0 -> target
    a.label(nz)                                   # v == 0 reached target


def add_val(a, slot, negval):
    """slot += negval  (slot = slot - (0-negval))  -- add via subtracting neg."""
    a.sq(a.const(negval), a.slot(slot))           # slot -= mem[const(negval)]


def copy_neg(a, dst_slot, src_slot):
    """dst = -src  (dst was 0)."""
    a.sq(a.slot(src_slot), a.slot(dst_slot))


# ---- core (BIOS) ----
def build_core():
    a = Asm()
    a.label('start')
    a.puts('oisk: core boot')
    a.puts('loading elfloader.ko from disk...')
    op = (1 << 24) | (KO_SECTORS << 16) | 0
    a.mmio_w('CMD', 14)
    a.mmio_w('DAT', LOAD_WORD)
    a.mmio_w('DAT', op)
    a.puts('ko loaded, jumping to elfloader')
    a.jmp(a.fixed('KO_ENTRY', LOAD_WORD))
    return a

# ---- kernel: elfloader.ko ----
def build_elfloader():
    a = Asm(base=LOAD_WORD)
    a.label('entry')
    a.fixed('K_A0', K_A0)
    a.fixed('K_RET', K_RET)

    a.puts('oisk: elfloader.ko (kernel)')

    # ---- ELF loader ------------------------------------------------
    # subleq A,B,C:  mem[B] -= mem[A] ; if mem[B] <= 0 (signed) PC = C
    # OISC memory is WORD addressed: DISK turns every 4 ELF bytes into one
    # 32-bit word, so everything below is in WORD units.
    #   word  0 = magic 0x464c457f      word  6 = e_entry (word addr)
    #   word  7 = e_phoff (word offset) word 11 = e_phnum
    #   phdr(8w): +0 p_type, +1 p_offset(w), +2 p_vaddr(w),
    #             +3 p_paddr(w), +4 p_filesz(w)
    a.mmio_w('CMD', 14)
    a.mmio_w('DAT', ELF_BASE)
    a.mmio_w('DAT', (1 << 24) | (INIT_SECTORS << 16) | KO_SECTORS)

    # --- magic check: d = magic - M ; d==0 -> ok ---------------------
    a.sq(a.slot('mg'), a.slot('mg'))                    # mg = 0
    a.sq(a.fixed('ELF_M0', ELF_BASE), a.slot('mg'))     # mg -= magic
    a.sq(a.const(-ELF_MAGIC_VAL), a.slot('mg'))         # mg += M
    # mg now = magic - M.  test exact zero:
    branch_zero(a, 'mg', 'magic_ok')
    a.sq(a.const(0), a.const(0), a.field_addr(L('elf_bad')))

    a.label('magic_ok')
    a.puts('init.elf: magic ok')

    # --- e_entry / e_phoff / e_phnum --------------------------------
    load_word(a, 'epn', ELF_BASE + 6)      # epn    = -e_entry
    load_word(a, 'phoffn', ELF_BASE + 7)   # phoffn = -e_phoff
    load_word(a, 'phnumn', ELF_BASE + 11)  # phnumn = -e_phnum

    # basen = -ELF_BASE   (subtract +ELF_BASE from 0)
    a.sq(a.slot('basen'), a.slot('basen'))
    a.sq(a.const(ELF_BASE), a.slot('basen'))

    # phcur = -(ELF_BASE + e_phoff) = -ELF_BASE - phoff
    #   phcur = 0 - ELF_BASE ; t = +phoff (0 - phoffn) ; phcur -= t
    a.sq(a.slot('phcur'), a.slot('phcur'))
    a.sq(a.const(ELF_BASE), a.slot('phcur'))
    a.sq(a.slot('t'), a.slot('t'))
    a.sq(a.slot('phoffn'), a.slot('t'))                 # t = +phoff
    a.sq(a.slot('t'), a.slot('phcur'))                  # phcur -= phoff

    a.sq(a.slot('idx'), a.slot('idx'))     # idx = 0

    a.label('ph_loop')
    # --- if idx >= phnum -> ph_done ---------------------------------
    # t = idx - phnum ;  t > 0 or t == 0 -> done ;  t < 0 -> body
    a.sq(a.slot('pn'), a.slot('pn'))
    a.sq(a.slot('phnumn'), a.slot('pn'))                # pn = phnum
    a.sq(a.slot('t'), a.slot('t'))
    a.sq(a.slot('idxn'), a.slot('idxn'))
    a.sq(a.slot('idx'), a.slot('idxn'))                 # idxn = -idx
    a.sq(a.slot('idxn'), a.slot('t'))                   # t = 0 - idxn = idx
    a.sq(a.slot('pn'), a.slot('t'))                     # t = idx - phnum
    # t <= 0 -> t_le0 ; else (t > 0) -> done
    a.sq(a.const(0), a.slot('t'), a.field_addr(L('ph_t_le0')))
    a.sq(a.const(0), a.const(0), a.field_addr(L('ph_done')))
    a.label('ph_t_le0')
    # t <= 0 : if t == 0 -> done (idx==phnum) ; else t<0 -> body
    branch_zero(a, 't', 'ph_done')

    # --- p_type = *phcur ; want p_type == 1 (PT_LOAD) ---------------
    a.sq(a.slot('tn'), a.slot('tn'))
    set_ptr(a, 'rd_t', 'phcur')
    a.label('rd_t')
    a.sq(a.field_addr(L('rd_t'), 0), a.slot('tn'), a.field_addr(L('rd_t2')))
    a.label('rd_t2')                                       # tn = -p_type
    # t = p_type - 1 ; t == 0 <-> PT_LOAD
    a.sq(a.slot('t'), a.slot('t'))
    a.sq(a.slot('tn'), a.slot('t'))                        # t = p_type
    a.sq(a.const(1), a.slot('t'))                          # t = p_type - 1
    branch_zero(a, 't', 'ph_type_ok')
    a.sq(a.const(0), a.const(0), a.field_addr(L('ph_next')))
    a.label('ph_type_ok')

    # p_offset(+1) / p_paddr(+3) / p_filesz(+4) : word units
    load_rel(a, 'pon', 1)
    load_rel(a, 'ppn', 3)
    load_rel(a, 'pfn', 4)

    # src = -(ELF_BASE + p_offset)   (src slot holds NEGATIVE address)
    #   t = +p_offset (0 - pon) ; src = -ELF_BASE ; src -= t
    a.sq(a.slot('t'), a.slot('t'))
    a.sq(a.slot('pon'), a.slot('t'))            # t = +p_offset
    a.sq(a.slot('src'), a.slot('src'))
    a.sq(a.const(ELF_BASE), a.slot('src'))      # src = -ELF_BASE
    a.sq(a.slot('t'), a.slot('src'))            # src = -ELF_BASE - p_offset
    # dst = -p_paddr   (dst slot holds NEGATIVE address)
    #   t = +p_paddr (0 - ppn) ; dst = -t
    a.sq(a.slot('t'), a.slot('t'))
    a.sq(a.slot('ppn'), a.slot('t'))            # t = +p_paddr
    a.sq(a.slot('dst'), a.slot('dst'))
    a.sq(a.slot('t'), a.slot('dst'))            # dst = -p_paddr
    # cn = -p_filesz   (negative word count; increments by 1 toward 0)
    #   t = +p_filesz (0 - pfn) ; cn = -t
    a.sq(a.slot('t'), a.slot('t'))
    a.sq(a.slot('pfn'), a.slot('t'))            # t = +p_filesz
    a.sq(a.slot('cn'), a.slot('cn'))
    a.sq(a.slot('t'), a.slot('cn'))             # cn = -p_filesz
    a.label('copy_loop')
    # cn == 0 -> done ; cn < 0 -> copy one more word.
    # IMPORTANT: plain `subleq ZERO,cn,done` jumps on cn<=0, i.e. ALSO on
    # cn<0, so the body would never run.  Use the exact-zero branch.
    branch_zero(a, 'cn', 'copy_done')
    # load word from src: wn = -mem[+src]
    a.sq(a.slot('wn'), a.slot('wn'))
    set_ptr(a, 'ld_w', 'src')
    a.label('ld_w')
    a.sq(a.field_addr(L('ld_w'), 0), a.slot('wn'), a.field_addr(L('ld_w2')))
    a.label('ld_w2')                                       # wn = -word
    # store word to dst: mem[+dst] = 0 - wn = word
    # subleq writes mem[B], so patch st_w's B FIELD to +dst, then
    #   A=wn, B=<dst>, C=next:  mem[dst] -= mem[wn] = 0 - (-word) = word
    set_ptrb(a, 'st_w', 'dst')
    a.label('st_w')
    a.sq(a.slot('wn'), a.field_addr(L('st_w'), 1),
         a.field_addr(L('st_w2')))
    a.label('st_w2')
    # advance one word : src -= 1 ; dst -= 1  (negated addr -> use const(1))
    a.sq(a.const(1), a.slot('src'))
    a.sq(a.const(1), a.slot('dst'))
    a.sq(a.const(-1), a.slot('cn'))      # cn += 1
    a.sq(a.const(0), a.const(0), a.field_addr(L('copy_loop')))
    a.label('copy_done')

    a.label('ph_next')
    # phcur = -addr ; advance addr by 8 words -> phcur -= 8 (use const(+8))
    a.sq(a.const(PHDR_WORDS), a.slot('phcur'))
    a.sq(a.const(-1), a.slot('idx'))     # idx += 1
    a.sq(a.const(0), a.const(0), a.field_addr(L('ph_loop')))

    a.label('ph_done')
    a.puts('init.elf: PT_LOAD segments loaded, jumping to e_entry')
    # dynamic jump to e_entry through the trampoline C field:
    #   mem[tplC] = 0 ; mem[tplC] = 0 - epn = e_entry ; jump tpl
    a.sq(a.field_addr(L('jmp_tpl'), 2), a.field_addr(L('jmp_tpl'), 2))
    a.sq(a.slot('epn'), a.field_addr(L('jmp_tpl'), 2))
    a.label('jmp_tpl')
    a.sq(a.const(0), a.const(0), a.const(0))

    a.label('elf_bad')
    a.puts('init.elf: BAD ELF MAGIC - halt')
    a.sq(a.const(0), a.const(0), a.const(0))



    # ---- srv_puts: print NUL-terminated string at k_A0 ----
    a.label('srv_puts')
    # np = -mem[K_A0]  (keep pointer NEGATED in slot 'np')
    a.sq(a.slot('np'), a.slot('np'))          # np = 0
    a.sq(a.fixed('K_A0', K_A0), a.slot('np')) # np = -P
    a.label('loop')
    # ch = 0  (char accumulator must be cleared every iteration)
    a.sq(a.slot('ch'), a.slot('ch'))
    # patch lda_cell's A field := +ptr (= 0 - np)
    # (a) A_field = 0   (must clear: initial value is field_addr's own addr,
    #     NOT zero -- omitting this corrupts the pointer)
    a.sq(a.field_addr(L('lda_cell'), 0), a.field_addr(L('lda_cell'), 0))
    # (b) A_field = 0 - mem[np] = 0 - (-P) = +P
    a.sq(a.slot('np'), a.field_addr(L('lda_cell'), 0))
    a.label('lda_cell')
    a.sq(a.field_addr(L('lda_cell'), 0), a.slot('ch'),
         a.field_addr(L('after_ld')))       # ch = -mem[ptr]; goto after_ld
    a.label('after_ld')
    a.sq(a.slot('c'), a.slot('c'))            # c = 0
    a.sq(a.slot('ch'), a.slot('c'))           # c = char (0 - (-char))
    a.sq(a.const(0), a.slot('c'), a.field_addr(L('done')))  # if c==0->done
    a.sq(a.slot('m'), a.slot('m'))            # m = 0
    a.sq(a.slot('c'), a.slot('m'))            # m = -char
    a.sq(a.slot('m'), a.reg('TX'))            # TX = char
    a.sq(a.const(1), a.slot('np'))            # np -= 1 (ptr += 1)
    a.sq(a.const(0), a.const(0), a.field_addr(L('loop')))
    a.label('done')
    # return via shared jump_dyn trampoline C field (tpl_cell+2):
    #   tplC = 0 ; tplC = 0 - k_RET = retaddr ; jump tpl
    a.sq(a.field_addr(L('tpl_cell'), 2), a.field_addr(L('tpl_cell'), 2))
    a.sq(a.fixed('K_RET', K_RET), a.field_addr(L('tpl_cell'), 2))
    a.sq(a.const(0), a.const(0), a.field_addr(L('tpl_cell'), 0))

    # ---- shared jump_dyn trampoline cell ----
    # subleq Z,Z,dynC : the C field (tpl_cell+2) is DYNAMICALLY patched
    # to the next target; the CPU jumps to whatever it holds.
    a.label('tpl_cell')
    a.sq(a.const(0), a.const(0), a.const(0))

    # ---- srv_exit: halt ----
    a.label('srv_exit')
    a.sq(a.const(0), a.const(0), a.const(0))
    return a


def emit_kcall(a, str_label, ret_label):
    """Emit a jump_dyn call site: print global string str_label, continue
    at ret_label.  Uses the SHARED trampoline cell in the kernel whose C
    field (tpl_cell+2) is dynamically patched to the next target."""
    # (1) tplC = 0                      subleq tplC, tplC
    a.sq(a.fixed('K_DYN', 0), a.fixed('K_DYN', 0))
    # (2) tplC = -patch_entry           subleq -patch, tplC
    a.sq(a.addr_of(L('kpatch_%s' % str_label), negate=True),
         a.fixed('K_DYN', 0))
    # (3) jump trampoline               subleq Z,Z,tpl  -> tplC(patch)
    a.sq(a.const(0), a.const(0), a.fixed('K_TPL', 0))
    a.label('kpatch_%s' % str_label)
    # patch: k_A0 = +str  (const pool holds -str: D = 0-(-str) = +str)
    a.sq(a.fixed('K_A0', K_A0), a.fixed('K_A0', K_A0))
    a.sq(a.addr_of(G(str_label), negate=True), a.fixed('K_A0', K_A0))
    # patch: k_RET = -retaddr  (const pool holds +ret: D = 0-(+ret) = -ret)
    a.sq(a.fixed('K_RET', K_RET), a.fixed('K_RET', K_RET))
    a.sq(a.addr_of(L(ret_label)), a.fixed('K_RET', K_RET))
    # patch: tplC = -srv_puts
    a.sq(a.fixed('K_DYN', 0), a.fixed('K_DYN', 0))
    a.sq(a.addr_of(C('K_SRV_PUTS'), negate=True), a.fixed('K_DYN', 0))
    # jump trampoline -> tplC(srv_puts)
    a.sq(a.const(0), a.const(0), a.fixed('K_TPL', 0))
    a.label(ret_label)


# ---- userland: init.elf ----
def build_init(extern_map):
    a = Asm(base=INIT_BASE)
    a.label('start')
    a.glob('msg1', 64)
    a.glob('msg2', 64)
    emit_kcall(a, 'msg1', 'ret1')
    emit_kcall(a, 'msg2', 'ret2')
    # exit via kernel: jump to srv_exit
    a.sq(a.const(0), a.const(0), a.fixed('K_EXIT', 0))
    words = a.build(extern_map)
    # back-patch string contents into glob data area
    glob_addr = {n: a.globs[n][1] for n in ('msg1', 'msg2')}
    str1 = 'hello from user space via kernel puts!\n'
    str2 = 'ko ABI: jump_dyn trampoline works.\n'
    for nm, s in (('msg1', str1), ('msg2', str2)):
        base = glob_addr[nm] - INIT_BASE
        assert base + len(s) < len(words), 'string too large for glob %s' % nm
        for i, ch in enumerate(s):
            words[base + i] = ord(ch) & 0xffffffff
    return a, words


def build_elf(entry, data):
    """Build a word-ELF (OISC convention).

    OISC memory is word addressed and the DISK command copies every 4 ELF
    bytes into one 32-bit word:  word[i] == file bytes[4i..4i+3].  So all
    offset/size/address fields are written as WORD units and the kernel
    loader can parse the image purely in words:
      word  0 = magic 0x464c457f
      word  6 = e_entry    (word address)
      word  7 = e_phoff    (word offset of phdr table)
      word 11 = e_phnum    (whole word; high half kept 0)
      phdr(8 words): p_type, p_offset(word), p_vaddr(word), p_paddr(word),
                     p_filesz(words), p_memsz(words), p_flags, p_align
    """
    nw = len(data) // 4            # payload word count
    e_phoff = 13                   # phdr table starts at word 13 (52 B /4)
    p_offset = e_phoff + 8         # payload starts at word 21 (84 B /4)

    hdr = struct.pack('<16sHHI', b'\x7fELF\x01\x01\x01\0', 2, 0x5a5a, 1)
    hdr += struct.pack('<II', entry, e_phoff)      # e_entry, e_phoff
    hdr += struct.pack('<II', 0, 0)                # e_shoff, e_flags
    hdr += struct.pack('<HH', 52, 32)              # e_ehsize, e_phentsize
    hdr += struct.pack('<HH', 1, 0)                # e_phnum=1, e_shentsize=0
    hdr += struct.pack('<HH', 0, 0)                # e_shnum, e_shstrndx
    assert len(hdr) == 52

    phdr = struct.pack('<IIIIIIII', 1, p_offset, entry, entry,
                       nw, nw, 7, 4)               # PT_LOAD seg
    elf = hdr + phdr + data
    while len(elf) % 512:
        elf += b'\0'
    return elf


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, 'out')
    os.makedirs(out, exist_ok=True)

    # ---- pass 1: core (BIOS) ----
    core = build_core()
    cw = core.build()
    core_path = os.path.join(out, 'oisk_core.bin')
    write_words(core_path, cw)
    print('core: %d words (%d B)' % (len(cw), len(cw) * 4))

    # ---- pass 1: elfloader.ko (kernel) ----
    ko = build_elfloader()
    kw = ko.build()
    ko_bin = b''.join(struct.pack('<I', w) for w in kw)
    print('ko:   %d words (%d B), labels=%s'
          % (len(kw), len(ko_bin), sorted(ko.labels)))
    if len(ko_bin) > KO_SECTORS * 512:
        raise ValueError('elfloader.ko too large: %d B > %d B'
                         % (len(ko_bin), KO_SECTORS * 512))
    tpl_addr = LOAD_WORD + ko.labels['tpl_cell']
    extern_map = {
        'K_SRV_PUTS': LOAD_WORD + ko.labels['srv_puts'],
        'K_TPL': tpl_addr,
        'K_DYN': tpl_addr + 2,
        'K_EXIT': LOAD_WORD + ko.labels['srv_exit'],
    }
    print('  kernel exports:', {k: hex(v) for k, v in extern_map.items()})

    # ---- pass 2: init.elf (userland) ----
    init, iw = build_init(extern_map)
    payload = b''.join(struct.pack('<I', w) for w in iw)
    elf = build_elf(INIT_BASE, payload)
    init_path = os.path.join(out, 'init.elf')
    open(init_path, 'wb').write(elf)
    print('init: %d words, elf %d B' % (len(iw), len(elf)))
    if len(elf) > INIT_SECTORS * 512:
        raise ValueError('init.elf too large: %d B > %d B'
                         % (len(elf), INIT_SECTORS * 512))

    # ---- disk image: ko@LBA0-3, init@LBA4+ ----
    hd = bytearray(64 * 512)
    hd[0:len(ko_bin)] = ko_bin
    hd[KO_SECTORS * 512:KO_SECTORS * 512 + len(elf)] = elf
    hd_path = os.path.join(out, 'oisk_hd.bin')
    open(hd_path, 'wb').write(hd)
    print('disk: %s (%d B), ko@LBA0, init@LBA4' % (hd_path, len(hd)))
    return 0


if __name__ == '__main__':
    sys.exit(main())