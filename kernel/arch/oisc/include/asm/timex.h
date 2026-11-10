/*
 * arch/oisc/include/asm/timex.h
 *
 * OISC timex interface (replaces openrisc's).  OISC has a free-running
 * 32-bit cycle counter at OISC_TIMER_COUNT (MMIO), which is also the
 * only clock the machine provides.
 */
#ifndef _OISC_ASM_TIMEX_H
#define _OISC_ASM_TIMEX_H

#include <asm/types.h>
#include <asm/oisc_hw.h>

/* cycles_t is a full 32-bit word on OISC. */
typedef u32 cycles_t;

/* Read the free-running cycle counter. */
#define get_cycles()      (*(u32 *)OISC_TIMER_COUNT)

#endif /* _OISC_ASM_TIMEX_H */