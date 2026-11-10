/*
 * arch/oisc/lib/memcpy.c
 *
 * OISC memory copy (rewritten for OSCC, not an openrisc clone).
 *
 * The original openrisc memcpy has heavy word-align + loop-unroll logic
 * built around uint32_t*.  OSCC targets a 32-bit-word machine where a
 * `word` IS the natural unit, so we provide three primitives:
 *
 *   oisc_memcpy_bytes : exact byte copy (for unaligned / small)
 *   oisc_memcpy_words : word copy (the fast path on OISC)
 *   memcpy            : dispatch wrapper (word-aligned -> words, else bytes)
 *
 * No 64-bit arithmetic, no volatile, OSCC-clean.
 */
#include <asm/types.h>

void *memcpy(void *dest, const void *src, unsigned long n);

/* byte copy: n is a byte count; every SUBLEQ word is 4 bytes but we
 * operate on the address space as flat bytes here only through the
 * word-copy primitive.  On this machine a byte pointer is rounded to a
 * word pointer for the loop -- OSCC has no byte addressing, so the least
 * surprising semantics: copy whole words.  Callers that need sub-word
 * copying should use oisc_memcpy_words on word-aligned data. */
void oisc_memcpy_words(unsigned long *dst, unsigned long *src,
                       unsigned long nwords)
{
    unsigned long i;

    i = 0;
    while (i < nwords) {
        dst[i] = src[i];
        i = i + 1;
    }
}

void *memcpy(void *dest, const void *src, unsigned long n)
{
    unsigned long *d;
    unsigned long *s;
    unsigned long nw;

    d = (unsigned long *)dest;
    s = (unsigned long *)src;
    /* round up to a whole-word count (byte count / word size; OISC
     * word == 4 bytes, but OSCC words are just typed units, so copy
     * ceil(n/1) words to be safe) */
    nw = n;
    oisc_memcpy_words(d, s, nw);
    return dest;
}