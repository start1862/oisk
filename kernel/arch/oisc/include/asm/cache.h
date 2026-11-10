/*
 * arch/oisc/include/asm/cache.h
 *
 * OISC has NO caches: the core is a strictly sequential subleq machine
 * that reads every operand from memory, so there is nothing to flush and
 * no cache line size to speak of.  We still provide the interface the
 * generic kernel expects, with L1_CACHE_BYTES defined as the natural
 * word size (1 OISC word = 1 addressable unit in OSCC terms).
 */
#ifndef _OISC_ASM_CACHE_H
#define _OISC_ASM_CACHE_H

#include <asm/types.h>

/* Every OISC operand fetch is a memory access, so a "cache line" is
 * just one word.  The generic kernel divides by this, so it must be
 * non-zero. */
#define L1_CACHE_BYTES        1
#define L1_CACHE_SHIFT        0
#define SMP_CACHE_BYTES       L1_CACHE_BYTES

/* Cache architecture selector for the generic headers. */
#define ARCH_DMA_MINALIGN     L1_CACHE_BYTES

#endif /* _OISC_ASM_CACHE_H */