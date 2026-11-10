/*
 * kernel/t_boot.c - driver for the minimal OISC kernel boot path.
 *
 * Merges arch/oisc/kernel/setup.c + start_kernel.c into one translation
 * unit (OSCC has no linker) and runs kernel_entry() on the simulator.
 * __oisc_putc/__oisc_puts are OSCC MMIO intrinsics (lowered to single-step
 * subleq writes into W_TX); the simulator captures them in s.out.
 * kernel_entry() spins forever in its idle loop, so main() below only
 * "returns" once max_steps is exhausted on the simulator; the boot bytes
 * are verified from s.out directly.
 */
#include <asm/types.h>
#include <asm/oisc_hw.h>
#include <asm/uart.h>
/* OSCC has no linker: merge the arch kernel sources into this TU so that
 * kernel_entry()/oisc_setup_arch() are defined before main() calls them. */
#include "arch/oisc/kernel/setup.c"
#include "arch/oisc/kernel/start_kernel.c"
int main(void)
{
    kernel_entry();
    return 1;   /* never reached (idle loop); sim stops on max_steps */
}