/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Minimal linux/string.h for the OISC port (OSCC subset).
 *
 * The OISC machine is word-addressed: every memory location is one 32-bit
 * word and even `char` occupies a full word.  The string/memory helpers are
 * therefore defined over WORDS, not bytes.  `n` in every prototype below is a
 * WORD count.  This diverges from upstream Linux but is exactly what the
 * hardware provides (there is no byte lane, no (void*)+1).
 */
#ifndef _LINUX_STRING_H
#define _LINUX_STRING_H

#include <linux/types.h>

/* copy n words from src to dest (dest/src may not overlap like memmove) */
void *memcpy(void *dest, const void *src, unsigned long n);

/* fill the first n words of dest with c */
void *memset(void *dest, int c, unsigned long n);

/* compare the first n words of two buffers; 0 if equal */
int memcmp(const void *a, const void *b, unsigned long n);

/* word-string length: number of non-zero words before a zero word */
unsigned long strlen(const char *s);

#endif /* _LINUX_STRING_H */