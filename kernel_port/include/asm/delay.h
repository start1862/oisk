/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * OISC architecture: delay interface (OSCC subset).
 *
 * Only prototypes live here.  Real kernels also declare static-inline
 * wrappers around __const_udelay; OSCC cannot inline and would bloat every
 * caller, so the wrappers are ordinary out-of-line functions defined in
 * lib/delay.c instead.
 */
#ifndef _ASM_OISC_DELAY_H
#define _ASM_OISC_DELAY_H

/* spin for at least `cycles` timer ticks */
void __delay(unsigned long cycles);

/* calibrated delay primitives, all ultimately call __delay */
void __const_udelay(unsigned long xloops);
void __udelay(unsigned long usecs);
void __ndelay(unsigned long nsecs);

#define udelay(n)     __udelay((n))
#define ndelay(n)     __ndelay((n))
#define mdelay(n)     __udelay((unsigned long)(n) * 1000UL)

#endif /* _ASM_OISC_DELAY_H */