#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""oishw.py - OISC hardware constants (word addresses).

QEMU machine hw/oisc/oisc.c maps MMIO at BYTE base OISC_IO_BASE=0xFFFF0000.
Operands in SUBLEQ are WORD addresses, so a word address W maps to byte
address W*4.  The MMIO registers are 4-byte word slots:

  byte 0x000 -> word 0x3FFFC000 : TX   (write byte to serial out)
  byte 0x004 -> word 0x3FFFC001 : RX   (read next input byte)
  byte 0x008 -> word 0x3FFFC002 : CMD  (write: start GPU command)
  byte 0x00C -> word 0x3FFFC003 : DAT  (write: one command word)
  byte 0x014 -> word 0x3FFFC005 : RES  (read: last command result)
  byte 0x01C -> word 0x3FFFC007 : CLK  (read: ms low 32)
  byte 0x020 -> word 0x3FFFC008 : CLKHI(read: ms high)
  byte 0x024 -> word 0x3FFFC009 : MX   (mouse x)
  byte 0x028 -> word 0x3FFFC00A : MY   (mouse y)
  byte 0x02C -> word 0x3FFFC00B : MB   (mouse buttons)
  byte 0x030 -> word 0x3FFFC00C : NET  (write 0 to send datagram)
  byte 0x034 -> word 0x3FFFC00D : DISK (write op word)

GPU commands (via CMD/DAT) - see oisc.c for details.
"""
W_TX = 0x3FFFC000
W_RX = 0x3FFFC001
W_CMD = 0x3FFFC002
W_DAT = 0x3FFFC003
W_RES = 0x3FFFC005
W_CLK = 0x3FFFC007
W_CLKHI = 0x3FFFC008
W_MX = 0x3FFFC009
W_MY = 0x3FFFC00A
W_MB = 0x3FFFC00B
W_NET = 0x3FFFC00C
W_DISK = 0x3FFFC00D

# FB is a framebuffer region in guest RAM at byte 0xFF000000
# (word address 0x3FC00000) - not used as MMIO.

# aliases used by assembler fallback
for _n in ('R_TX', 'R_RX', 'R_CMD', 'R_DAT', 'R_RES', 'R_CLK', 'R_CLKHI',
           'R_MX', 'R_MY', 'R_MB', 'R_NET', 'R_DISK'):
    globals()[_n] = globals()['W' + _n[1:]]