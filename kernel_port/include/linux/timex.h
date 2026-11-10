/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Minimal linux/timex.h for the OISC port (OSCC subset).
 *
 * Upstream this header carries the NTP/PLL state machine and a pile of clock
 * arithmetic.  The OISC port starts with the single piece the delay path
 * needs: the loops_per_jiffy calibration variable that __const_udelay scales
 * by.  Everything else is added only when a consumer actually appears.
 */
#ifndef _LINUX_TIMEX_H
#define _LINUX_TIMEX_H

#include <asm/param.h>

/*
 * loops_per_jiffy: calibrated busy-loop count for one timer tick.
 * Declared here (definition lives in the timer init path) because
 * __const_udelay() multiplies by it.
 */
extern unsigned long loops_per_jiffy;

#endif /* _LINUX_TIMEX_H */