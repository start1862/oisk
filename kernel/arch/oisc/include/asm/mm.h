/*
 * arch/oisc/include/asm/mm.h
 *
 * Minimal physical page allocator for OISC.
 *
 * OSCC note: no bitwise OR (!), so a free-list is used instead of a
 * bitmap.  Blocks live in a fixed array (MM_MAX_BLOCKS) and form a
 * singly-linked list through 1-based "next" indices (0 = end/NULL).
 * Addresses are BYTE addresses (4-aligned; one page = 4096 bytes).
 */
#ifndef _OISC_ASM_MM_H
#define _OISC_ASM_MM_H
#include <asm/types.h>

#define MM_PAGE_SIZE    4096
#define MM_MAX_BLOCKS   32

struct mm_block {
    u32 base;   /* byte address of the block */
    u32 size;   /* size in bytes */
    u32 next;   /* 1-based index of next block, 0 = end */
    u32 used;   /* 1 = live block/list node, 0 = free slot */
};

void mm_init(u32 base, u32 size);
u32 mm_alloc_page(void);
void mm_free_page(u32 addr);
u32 mm_free_count(void);
u32 mm_alloc_count(void);
#endif /* _OISC_ASM_MM_H */