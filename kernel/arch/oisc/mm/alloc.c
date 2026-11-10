/*
 * arch/oisc/mm/alloc.c
 *
 * OISC physical memory free-list allocator (OSCC-clean).
 *
 * A single big free block is created by mm_init(); allocation walks the
 * list first-fit and carves MM_PAGE_SIZE off the front of a block
 * (splitting the remainder back into the list).  Freeing appends a new
 * node to the tail.  No coalescing yet -- good enough for the boot
 * milestone and easy to extend later.
 */
#include <asm/types.h>
#include <asm/mm.h>

struct mm_block g_blocks[MM_MAX_BLOCKS];
u32 g_mm_head;          /* 1-based index of first block, 0 = empty */
u32 g_mm_free_count;
u32 g_mm_alloc_count;

void mm_init(u32 base, u32 size)
{
    u32 i;
    for (i = 0; i < MM_MAX_BLOCKS; i = i + 1) {
        g_blocks[i].base = 0;
        g_blocks[i].size = 0;
        g_blocks[i].next = 0;
        g_blocks[i].used = 0;
    }
    g_blocks[0].base = base;
    g_blocks[0].size = size;
    g_blocks[0].next = 0;
    g_blocks[0].used = 1;
    g_mm_head = 1;
    g_mm_free_count = 1;
    g_mm_alloc_count = 0;
}

/* Return a byte address of a fresh page, or 0 on failure. */
u32 mm_alloc_page(void)
{
    u32 prev;   /* 1-based index of previous node, 0 = none */
    u32 cur;
    u32 idx;
    u32 addr;
    prev = 0;
    cur = g_mm_head;
    while (cur != 0) {
        idx = cur - 1;
        if (g_blocks[idx].size >= MM_PAGE_SIZE) {
            addr = g_blocks[idx].base;
            g_blocks[idx].base = addr + MM_PAGE_SIZE;
            g_blocks[idx].size = g_blocks[idx].size - MM_PAGE_SIZE;
            if (g_blocks[idx].size == 0) {
                /* unlink the exhausted node and free its slot */
                if (prev == 0)
                    g_mm_head = g_blocks[idx].next;
                else
                    g_blocks[prev - 1].next = g_blocks[idx].next;
                g_blocks[idx].base = 0;
                g_blocks[idx].size = 0;
                g_blocks[idx].next = 0;
                g_blocks[idx].used = 0;
                g_mm_free_count = g_mm_free_count - 1;
            }
            g_mm_alloc_count = g_mm_alloc_count + 1;
            return addr;
        }
        prev = cur;
        cur = g_blocks[idx].next;
    }
    return 0;
}

void mm_free_page(u32 addr)
{
    u32 i;
    u32 old;
    if (addr == 0)
        return;
    i = 0;
    while (i < MM_MAX_BLOCKS) {
        if (g_blocks[i].used == 0) {
            g_blocks[i].base = addr;
            g_blocks[i].size = MM_PAGE_SIZE;
            g_blocks[i].used = 1;
            /* prepend to head: no list traversal, no cur local --
             * the OSCC codegen for tail-append (g_blocks[cur-1].next)
             * was observed to corrupt idx/cur (self-loop) */
            old = g_mm_head;
            g_blocks[i].next = old;
            g_mm_head = i + 1;
            g_mm_free_count = g_mm_free_count + 1;
            return;
        }
        i = i + 1;
    }
    /* no free slot: leaked page (caller should not hit this in boot) */
}

u32 mm_free_count(void)
{
    return g_mm_free_count;
}
u32 mm_alloc_count(void)
{
    return g_mm_alloc_count;
}