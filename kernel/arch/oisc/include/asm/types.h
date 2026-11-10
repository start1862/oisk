/*
 * arch/oisc/include/asm/types.h
 *
 * OISC kernel base types.
 *
 * OSCC note: only the subset of kernel types expressible in OSCC's C subset
 * is provided here (no 64-bit, no volatile, no bitfields).  `unsigned long`
 * is a word in SUBLEQ-land, so u32/unsigned long all map to a single word.
 */
#ifndef _OISC_ASM_TYPES_H
#define _OISC_ASM_TYPES_H

typedef unsigned char  u8;
typedef unsigned int   u32;
typedef int            s32;
typedef unsigned long  ulong;

#define NULL  0
#define true  1
#define false 0

/* OISC word is 32 bits; PAGE_SIZE = 4096 bytes = 1024 words. */
#define PAGE_SIZE       4096
#define PAGE_SHIFT      12
#define PAGE_MASK       (~(PAGE_SIZE - 1))

#endif /* _OISC_ASM_TYPES_H */