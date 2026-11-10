/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Standalone test harness for kernel_port/lib/delay.c.
 *
 * Supplies the tiny set of stubs the delay code reaches for (cycle counter
 * read, cpu_relax, loops_per_jiffy) and then exercises every public delay
 * entry point with small values so the simulator terminates quickly:
 *   - __delay(0)      must return instantly
 *   - __delay(3)      must spin but always terminate
 *   - __udelay(1)
 *   - __ndelay(1)
 *   - __const_udelay(1)
 *   - read_current_timer(&x)
 * Finally checks a globals snapshot that proves the calls ran.
 */
#include <asm/processor.h>
#include <linux/types.h>

/* ---- stubs supplied by the test harness ---- */
unsigned long loops_per_jiffy;

unsigned long oisc_get_cycles(void)
{
	/* fixed fake counter that never advances: loops still terminate */
	return 4;
}

void cpu_relax(void)
{
	/* no-op on OISC */
}

/* ---- counters for end-of-test checks ---- */
unsigned long ran_delay;
unsigned long ran_udelay;
unsigned long ran_ndelay;
unsigned long ran_constud;
unsigned long timer_val;
unsigned long g_delay2;

/* ---- include the delay implementation as one TU ---- */
#include "/opt/oisk/kernel_port/lib/delay.c"

int main(void)
{
	unsigned long t;

	/* 0-tick delay: must not hang */
	__delay(0);
	ran_delay = 1;

	/* very small busy loop that terminates */
	__delay(2);
	g_delay2 = 2;

	__udelay(1);
	ran_udelay = 1;

	__ndelay(1);
	ran_ndelay = 1;

	__const_udelay(1);
	ran_constud = 1;

	read_current_timer(&t);
	timer_val = t;

	return 0;
}