/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * OISC (SUBLEQ) architecture: processor primitives.
 *
 * This is the *OSCC-compilable* dialect of the header.  GCC-only constructs
 * (__asm__ barriers, volatile qualifiers, inline keyword) are replaced by
 * plain C because OSCC's parser has no notion of them; the OISC machine model
 * makes them semantically unnecessary anyway:
 *   - no store buffer  -> no compiler/hardware barrier needed
 *   - no cache         -> no cache maintenance in the hot path
 *   - single in-order  -> no speculative reload of the cycle counter
 *
 * The simulated CPU keeps a monotonic 32-bit cycle counter at a fixed word
 * address; OSIM increments it once per executed SUBLEQ instruction, so it
 * doubles as an instruction counter.
 */
#ifndef _ASM_OISC_PROCESSOR_H
#define _ASM_OISC_PROCESSOR_H

#define OISC_CYCLE_COUNTER_ADDR  0x0000FFF0

/* read the free-running cycle/instruction counter */
unsigned long oisc_get_cycles(void);

#define get_cycles()  oisc_get_cycles()

/*
 * OISC has no speculative execution and a single outstanding memory access,
 * so cpu_relax() is semantically a no-op.  It is kept as a real call target
 * so delay loops still have something to invoke per iteration.
 */
void cpu_relax(void);

#endif /* _ASM_OISC_PROCESSOR_H */