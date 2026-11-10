/*
 * arch/oisc/include/asm/uart.h
 *
 * Minimal OISC serial driver header.
 *
 * The UART is a single MMIO word: writing a byte to OISC_UART_TX emits it
 * on serial out.  Because the plain C store path (st()) zeroes its target
 * first (subleq dst,dst), a direct `*(volatile u32*)OISC_UART_TX = c`
 * would ALSO hit the write port with 0x00 -- a ghost byte.  Kernel code
 * therefore goes through the __oisc_putc/__oisc_puts intrinsics, which
 * OSCC lowers to a single-step subleq (tmp=-c; subleq tmp,TX) that reads 0
 * back and writes exactly one byte.
 */
#ifndef _OISC_ASM_UART_H
#define _OISC_ASM_UART_H

#include <asm/oisc_hw.h>
#include <asm/types.h>

/* Intrinsics supplied by OSCC (must be declared for the parser). */
void __oisc_putc(int c);
void __oisc_puts(char *s);

/* ---- byte-at-a-time helpers ---- */
static inline void uart_putc(u32 c)
{
    __oisc_putc(c);
}

static inline void uart_puts(const char *s)
{
    char *p;
    p = (char *)s;
    __oisc_puts(p);
}

static inline void uart_puthex4(u32 v)
{
    u32 d;
    d = v % 16;
    if (d < 10)
        uart_putc('0' + d);
    else
        uart_putc('A' + d - 10);
}

/*
 * OISC has no division instruction; OSCC's % and / lower to subtractive
 * loops whose cost is O(quotient).  For a 32-bit value, x&0xf and x>>4
 * would be even more expensive (mod-by-2 loops over half the value range),
 * so we extract hex digits with %16 and /16 -- semantically identical for
 * the non-negative u32 here, and the total loop cost across all 8 digits
 * is only ~ value/16 + /256 + ... bounded by a few million steps.
 */
static inline void uart_puthex(u32 v)
{
    u32 digits[8];
    u32 i;
    u32 d;
    for (i = 0; i < 8; i = i + 1) {
        d = v % 16;
        digits[i] = d;
        v = v / 16;
    }
    for (i = 0; i < 8; i = i + 1) {
        d = digits[7 - i];
        if (d < 10)
            uart_putc('0' + d);
        else
            uart_putc('A' + d - 10);
    }
}

static inline void uart_putnl(void)
{
    uart_putc('\n');
}

#endif /* _OISC_ASM_UART_H */