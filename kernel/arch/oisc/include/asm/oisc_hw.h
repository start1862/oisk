/*
 * arch/oisc/include/asm/oisc_hw.h
 *
 * OISC hardware abstraction.
 *
 * Replaces openrisc's spr_defs.h / processor.h / mmu.h.  SUBLEQ has no
 * special-purpose registers: all CPU state (PC, SP, flags, interrupt mask)
 * lives in fixed memory words at the bottom of the address space, and
 * MMIO devices are simply memory ranges.
 */
#ifndef _OISC_ASM_HW_H
#define _OISC_ASM_HW_H

#include <asm/types.h>

/* ---- fixed CPU state words ------------------------------------------- */
/* These absolute addresses form the OISC "register file".  Trap handlers
 * and context switches (arch/oisc/kernel/entry.c) read/write them directly,
 * exactly the way a normal port touches its CPU registers. */
#define OISC_REG_BASE       0x00000000
#define OISC_PC             0x00000000   /* program counter */
#define OISC_SP             0x00000001   /* stack pointer */
#define OISC_FLAGS          0x00000002   /* Z/N/C/V flags packed */
#define OISC_IRQ_MASK       0x00000003   /* interrupt mask */
#define OISC_FAULT_ADDR     0x00000004   /* last faulting address */
#define OISC_FAULT_CODE     0x00000005   /* last fault cause */

/* ---- MMIO device map ------------------------------------------------- */
/* IMPORTANT: these are WORD addresses, matching oishw.py / sim.py and the
 * QEMU machine (oisc.c maps MMIO at byte 0xFFFF0000; a SUBLEQ word address
 * W maps to byte W*4, so the UART window is the top 64 words of the
 * 32-bit address space).  TX/RX/STATUS are one word apart. */
#define OISC_UART_BASE      0x3FFFC000   /* word base of UART window */
#define OISC_UART_TX        0x3FFFC000   /* write byte -> serial out */
#define OISC_UART_RX        0x3FFFC001   /* read next input byte */
#define OISC_UART_STATUS    0x3FFFC002   /* status (TX busy etc.) */

#define OISC_TIMER_BASE     0x00101000
#define OISC_TIMER_COUNT    0x00101000
#define OISC_TIMER_COMPARE  0x00101004

#define OISC_IRQ_BASE       0x00102000
#define OISC_IRQ_PENDING    0x00102000
#define OISC_IRQ_ACK        0x00102004

/* ---- architectural helpers ------------------------------------------- */
/* cpu_relax: on a sequential-subleq machine the cheapest "relax" is a
 * load of the fixed zero word, which is what the simulator itself uses
 * as its no-op cell. */
#define cpu_relax()         (*(volatile u32 *)0 != 0)

/* Memory barriers are no-ops on a strictly sequential OISC core. */
#define mb()
#define rmb()
#define wmb()
#define barrier()

#endif /* _OISC_ASM_HW_H */