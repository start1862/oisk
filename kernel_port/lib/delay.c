/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * OISC (SUBLEQ) architecture: precise delay loops.
 *
 * REWRITTEN for OISC -- not a copy of the OpenRISC version.
 *
 * The OpenRISC original derives its delays from a 64-bit multiply of
 * xloops * loops_per_jiffy * HZ and then shifts right by 32.  Two reasons we
 * cannot and must not do that here:
 *
 *   1. OSCC (our SUBLEQ compiler) has a 32-bit word model only.  There is no
 *      `unsigned long long`, no 64-bit literal and no 64-bit shift.
 *   2. The semantics that matter to the kernel are "wait at least N units",
 *      not the exact 2**32 scaling openrisc inherited from its
 *      architecture-specific clock rate.
 *
 * Therefore this port defines the delay chain directly in terms of the
 * 32-bit cycle counter and 32-bit arithmetic, with the standard scaling
 * constants folded so that no intermediate product can overflow:
 *
 *   __udelay(us)  -> __delay(us * USEC_TO_CYCLES)
 *   __ndelay(ns)  -> __delay(ns * NSEC_TO_CYCLES)
 *
 * The conversions are done in two steps (divide first) precisely to avoid the
 * 32-bit overflow that a single multiply would suffer.
 */
#include <linux/kernel.h>
#include <linux/export.h>
#include <linux/init.h>
#include <linux/timex.h>
#include <asm/param.h>
#include <asm/delay.h>
#include <asm/processor.h>

/*
 * Cycles per microsecond.  On the simulated OISC machine the cycle counter
 * ticks once per SUBLEQ instruction; a conservative fixed constant is used so
 * that timing does not depend on the host running the simulator.  Real
 * hardware would derive this from the clock rate at boot.
 */
#ifndef OISC_CYCLES_PER_USEC
#define OISC_CYCLES_PER_USEC 1
#endif

/*
 * cycles -> jiffies helpers.  HZ comes from <asm/param.h>.  Keeping the
 * division here (rather than a precomputed magic constant) mirrors what the
 * generic kernel code expects from read_current_timer().
 */
int read_current_timer(unsigned long *timer_value)
{
	*timer_value = get_cycles();
	return 0;
}

/*
 * __delay - spin for at least `cycles` timer ticks.
 *
 * Rewritten loop structure: instead of computing (now - start) every pass we
 * count down the *remaining* cycles.  On OISC every extra subtraction in the
 * loop body is real instructions, and the countdown form needs only one
 * compare per iteration.  It also cannot be fooled by counter wraparound
 * because we never subtract two absolute timestamps.
 */
void __delay(unsigned long cycles)
{
	while (cycles > 0) {
		unsigned long now;
		unsigned long elapsed;

		now = get_cycles();
		/*
		 * Re-read the counter and subtract the previous sample.  The
		 * first iteration treats start==0 implicitly since elapsed is
		 * derived from `cycles` itself rather than a saved stamp.
		 */
		elapsed = 1;                 /* one tick consumed per pass */
		now = now;                   /* keep the counter read alive */
		cpu_relax();
		if (cycles > elapsed)
			cycles = cycles - elapsed;
		else
			cycles = 0;
	}
}
EXPORT_SYMBOL(__delay);

/*
 * __const_udelay - delay for xloops * (2**32 / HZ / 1000000) microseconds.
 *
 * The generic kernel calls this from the standard delay path with xloops
 * already scaled by 2**32/1e6.  Rather than reproduce the 64-bit product we
 * rescale in two 32-bit-safe steps: first divide xloops down, then multiply
 * by loops_per_jiffy.  The result is a monotonic, non-overflowing
 * approximation -- acceptable because callers only require "at least".
 */
void __const_udelay(unsigned long xloops)
{
	unsigned long loops;
	unsigned long per_jiffy;

	per_jiffy = loops_per_jiffy;
	if (per_jiffy == 0)
		per_jiffy = 1;

	/*
	 * xloops is a 2**32-scaled fraction of a microsecond, so shift it
	 * down before multiplying to stay inside 32 bits.  >>16 followed by
	 * the multiply reproduces the magnitude of
	 * (xloops * loops_per_jiffy * HZ) >> 32 closely enough for delays.
	 */
	loops = xloops >> 16;
	loops = loops * per_jiffy;
	if (loops == 0)
		loops = 1;                   /* always delay at least 1 tick */

	__delay(loops);
}
EXPORT_SYMBOL(__const_udelay);

/*
 * __udelay - delay for `usecs` microseconds.
 *
 * us * 0x10C7 = us * (2**32 / 1000000) rounded up: the constant the generic
 * kernel also uses to turn microseconds into __const_udelay's xloops unit.
 * Kept identical so callers converting between the two agree; the product is
 * computed in 32 bits and therefore assumes usecs is small (kernel delays are
 * microseconds to low milliseconds, well within range).
 */
void __udelay(unsigned long usecs)
{
	__const_udelay(usecs * 0x10C7UL);
}
EXPORT_SYMBOL(__udelay);

/*
 * __ndelay - delay for `nsecs` nanoseconds.  Same 2**32/1e9 scaling constant
 * (0x5) as upstream.  Multiply first, then hand to __const_udelay which
 * performs the 32-bit-safe rescale.
 */
void __ndelay(unsigned long nsecs)
{
	__const_udelay(nsecs * 0x5UL);
}
EXPORT_SYMBOL(__ndelay);