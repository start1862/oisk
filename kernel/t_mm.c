/*
 * kernel/t_mm.c - driver for arch/oisc/mm/alloc.c
 *
 * Merged single TU (OSCC has no linker): arch/oisc/mm/alloc.c + this file.
 * Exercises first-fit page allocation, free, hole reuse and exhaustion.
 * Landmark globals are read back by tests/kernel_test.py.
 *
 * Layout: 8 pages starting at 0x10000000 -> p0..p7 contiguous; the 9th
 * alloc must fail (0); freeing p2/p5 creates two 1-page holes which must
 * be reusable.
 */
#include <asm/types.h>
#include <asm/mm.h>
/* OSCC has no linker: merge the allocator source into this TU. */
#include "arch/oisc/mm/alloc.c"

u32 g_p0;
u32 g_p1;
u32 g_p2;
u32 g_p3;
u32 g_p4;
u32 g_p5;
u32 g_p6;
u32 g_p7;
u32 g_p8;
u32 g_free0;   /* free_count after mm_init          (expect 1) */
u32 g_free1;   /* free_count after 8 allocs         (expect 0) */
u32 g_free2;   /* free_count after freeing p2,p5    (expect 2) */
u32 g_free3;   /* free_count after reusing both     (expect 0) */
u32 g_alloc1;  /* alloc_count after 8 allocs        (expect 8) */
u32 g_alloc2;  /* alloc_count after 2 more allocs   (expect 10) */
u32 g_r1;      /* address returned for first hole  */
u32 g_r2;      /* address returned for second hole */
u32 g_fail;    /* 1 if any check fails */

int main()
{
    mm_init(0x10000000, 8 * 4096);
    g_free0 = mm_free_count();

    g_p0 = mm_alloc_page();
    g_p1 = mm_alloc_page();
    g_p2 = mm_alloc_page();
    g_p3 = mm_alloc_page();
    g_p4 = mm_alloc_page();
    g_p5 = mm_alloc_page();
    g_p6 = mm_alloc_page();
    g_p7 = mm_alloc_page();
    g_p8 = mm_alloc_page();          /* must fail: pool exhausted */
    g_alloc1 = mm_alloc_count();

    if (g_p0 != 0x10000000) g_fail = 1;
    if (g_p1 != 0x10001000) g_fail = 1;
    if (g_p2 != 0x10002000) g_fail = 1;
    if (g_p3 != 0x10003000) g_fail = 1;
    if (g_p4 != 0x10004000) g_fail = 1;
    if (g_p5 != 0x10005000) g_fail = 1;
    if (g_p6 != 0x10006000) g_fail = 1;
    if (g_p7 != 0x10007000) g_fail = 1;
    if (g_p8 != 0)          g_fail = 1;
    g_free1 = mm_free_count();
    if (g_free1 != 0)       g_fail = 1;
    if (g_alloc1 != 8)      g_fail = 1;

    /* free two interior pages -> two holes */
    mm_free_page(g_p2);
    mm_free_page(g_p5);
    g_free2 = mm_free_count();
    if (g_free2 != 2)       g_fail = 1;

    /* reuse the holes (first-fit walks head, picks the two 1-page nodes) */
    g_r1 = mm_alloc_page();
    g_r2 = mm_alloc_page();
    g_alloc2 = mm_alloc_count();
    g_free3 = mm_free_count();
    if (g_r1 == 0 || g_r2 == 0)  g_fail = 1;
    if (g_free3 != 0)            g_fail = 1;
    if (g_alloc2 != 10)          g_fail = 1;
    return 0;
}