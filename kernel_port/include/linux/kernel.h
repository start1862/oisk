/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Minimal linux/kernel.h for the OISC port (OSCC subset).
 *
 * Holds only what arch/oisc code actually reaches for.  The real header drags
 * in container_of, ARRAY_SIZE, min/max macros and the printk family; OSCC has
 * no variadic functions and no macro-generated statement expressions, so those
 * are provided as plain macros (or omitted until needed).
 */
#ifndef _LINUX_KERNEL_H
#define _LINUX_KERNEL_H

#include <linux/types.h>

#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))

#define min(a, b) ((a) < (b) ? (a) : (b))
#define max(a, b) ((a) > (b) ? (a) : (b))

/* basic clamp helpers used by delay/timer code paths */
#define min_t(t, a, b) ((t)(a) < (t)(b) ? (t)(a) : (t)(b))
#define max_t(t, a, b) ((t)(a) > (t)(b) ? (t)(a) : (t)(b))

#endif /* _LINUX_KERNEL_H */