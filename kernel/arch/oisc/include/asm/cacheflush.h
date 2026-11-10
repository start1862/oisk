/*
 * arch/oisc/include/asm/cacheflush.h
 *
 * OISC cache flush interface.  On a machine with no caches every flush
 * is a no-op, but the functions must EXIST because generic kernel code
 * (mm/, fs/, drivers) calls them unconditionally.
 *
 * Kept as plain functions (not macros) so OSCC compiles them normally and
 * the symbol names stay available for future linking.
 */
#ifndef _OISC_ASM_CACHEFLUSH_H
#define _OISC_ASM_CACHEFLUSH_H

#include <asm/types.h>
#include <asm/cache.h>

/* Flush a whole page's worth of data cache.  No-op on OISC. */
static inline void local_dcache_page_flush(void *page)
{
    (void)page;
}

/* Invalidate a whole page's worth of instruction cache.  No-op on OISC. */
static inline void local_icache_page_inv(void *page)
{
    (void)page;
}

/* Flush the entire data cache.  No-op. */
static inline void flush_dcache_all(void)
{
}

/* Invalidate the entire instruction cache.  No-op. */
static inline void flush_icache_all(void)
{
}

/* Flush one address range; called on every page mapping change. */
static inline void flush_dcache_range(unsigned long start,
                                      unsigned long end)
{
    (void)start;
    (void)end;
}

static inline void flush_icache_range(unsigned long start,
                                      unsigned long end)
{
    (void)start;
    (void)end;
}

/* Generic alias used all over the kernel. */
#define flush_cache_all()              do { } while (0)
#define flush_cache_mm(mm)             do { } while (0)
#define flush_cache_page(vma, addr, pfn) do { } while (0)
#define flush_cache_range(vma, start, end) do { } while (0)
#define flush_tlb_all()                do { } while (0)

/* sync_icache_dcache: keep icache coherent with a freshly written page.
 * Nothing to do on OISC (unified memory, no icache). */
static inline void sync_icache_dcache(void *page)
{
    (void)page;
}

#endif /* _OISC_ASM_CACHEFLUSH_H */