/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * OISC architecture: kernel parameters (OSCC subset).
 *
 * HZ is the timer interrupt frequency used by the kernel's jiffy logic.
 * The OISC simulator exposes a cycle counter that ticks once per executed
 * SUBLEQ instruction; we run the simulated kernel with a modest HZ so that
 * timer accounting does not flood the simulator with interrupts.
 */
#ifndef _ASM_OISC_PARAM_H
#define _ASM_OISC_PARAM_H

#define HZ 100

/*
 * Number of scheduler ticks per second accounted in loops_per_jiffy.
 * Kept as a plain integer global so delay loops can be compiled and
 * exercised standalone; the real boot path calibrates it.
 */
extern unsigned long loops_per_jiffy;

#ifndef __ASSEMBLY__
#define MAX_THREADS 64
#endif

#endif /* _ASM_OISC_PARAM_H */