/*
 * arch/oisc/include/asm/delay.h
 *
 * OISC delay loop interface.  Replaces openrisc's delay.h; OISC has no
 * 64-bit arithmetic in OSCC, so all delays are computed with 32-bit
 * cycle counts.
 */
#ifndef _OISC_ASM_DELAY_H
#define _OISC_ASM_DELAY_H

#include <asm/types.h>

/* HZ / loops_per_jiffy are supplied by the kernel core; the delay code
 * only needs their product to fit in 32 bits on this machine. */
extern unsigned long loops_per_jiffy;
extern u32 jiffies_hz;

void __delay(unsigned long cycles);
void __udelay(unsigned long usecs);
void __ndelay(unsigned long nsecs);

#endif /* _OISC_ASM_DELAY_H */