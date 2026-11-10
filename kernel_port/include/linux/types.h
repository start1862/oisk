/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Minimal linux/types.h for the OISC port (OSCC subset).
 *
 * The OISC machine is a pure 32-bit-word SUBLEQ engine: every memory cell is
 * one 32-bit signed word, addresses are word indices, and there is no notion
 * of 8/16-bit storage.  The typedefs below therefore collapse the usual C
 * integer zoo onto the single 32-bit word the hardware actually has.
 *
 * Consequences worth remembering when porting kernel code:
 *   - char is 32 bits, so byte-oriented code must be rewritten, not adapted;
 *   - there is no 64-bit type at all (no long long / __u64);
 *   - a "pointer" is just a word holding another word's index.
 */
#ifndef _LINUX_TYPES_H
#define _LINUX_TYPES_H

typedef unsigned int        __u32;
typedef int                 __s32;
typedef unsigned int        __u16;   /* no narrower storage: same word */
typedef int                 __s16;
typedef unsigned int        __u8;
typedef int                 __s8;

typedef __u32               u32;
typedef __s32               s32;
typedef __u16               u16;
typedef __s16               s16;
typedef __u8                u8;
typedef __s8                s8;

typedef unsigned int        uint;
typedef unsigned long       ulong;

/* the kernel's fundamental size/offset type on OISC: one word */
typedef unsigned int        size_t;
typedef int                 ssize_t;
typedef int                 ptrdiff_t;

typedef unsigned int        phys_addr_t;
typedef unsigned int        dma_addr_t;

#ifndef NULL
#define NULL ((void *)0)
#endif

/* boolean type; C has no <stdbool.h> in OSCC's subset */
typedef int                 bool;
#define true  1
#define false 0

#endif /* _LINUX_TYPES_H */