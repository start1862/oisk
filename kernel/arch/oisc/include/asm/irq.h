/*
 * arch/oisc/include/asm/irq.h
 *
 * OISC interrupt interface (replaces openrisc's SPR-based irqflags).
 *
 * OISC keeps the interrupt mask in a fixed memory word (OISC_IRQ_MASK).
 * The architecture defines exactly one interrupt-enabled bit, IRQ_EN, in
 * that word.  arch_local_irq_* below manipulate it directly.
 */
#ifndef _OISC_ASM_IRQ_H
#define _OISC_ASM_IRQ_H

#include <asm/types.h>
#include <asm/oisc_hw.h>

/* Interrupt enable bit inside the IRQ mask word. */
#define IRQ_EN   1

/* The flags value that means "interrupts enabled". */
#define IRQ_FLAG_ENABLED   IRQ_EN

typedef u32 irqflags_t;

/* Save current IRQ enable state. */
static inline irqflags_t arch_local_save_flags(void)
{
    return *(u32 *)OISC_IRQ_MASK;
}

/* Restore a previously saved IRQ enable state. */
static inline void arch_local_irq_restore(irqflags_t flags)
{
    *(u32 *)OISC_IRQ_MASK = flags;
}

/* Disable IRQs; do not save state. */
static inline void arch_local_irq_disable(void)
{
    *(u32 *)OISC_IRQ_MASK = 0;
}

/* Enable IRQs; do not save state. */
static inline void arch_local_irq_enable(void)
{
    *(u32 *)OISC_IRQ_MASK = IRQ_FLAG_ENABLED;
}

/* Save state AND disable IRQs (the common critical-section entry). */
static inline irqflags_t arch_local_irq_save(void)
{
    irqflags_t flags = arch_local_save_flags();
    arch_local_irq_disable();
    return flags;
}

#endif /* _OISC_ASM_IRQ_H */