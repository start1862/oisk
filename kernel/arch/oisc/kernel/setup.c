/*
 * arch/oisc/kernel/setup.c
 *
 * Minimal OISC architecture setup: reports the DRAM size, initialises the
 * early serial console and prints the boot banner.  Mirrors the role of
 * setup_arch() on real ports but sized for the OSCC subset (single
 * translation unit, no linker, u32 world).
 */
#include <asm/types.h>
#include <asm/oisc_hw.h>
#include <asm/uart.h>
#include <asm/timex.h>

/* Physical DRAM size in bytes (sim/oishw machine has 64 MiB). */
u32 oisc_memory_size;

/*
 * oisc_setup_arch: called before the main kernel starts.  On OISC there is
 * no MMU, no cache and no per-CPU programming to do -- the interesting work
 * is publishing the memory size and getting a console up.
 */
void oisc_setup_arch(void)
{
    u32 mb;
    oisc_memory_size = 64 * 1024 * 1024;
    mb = oisc_memory_size / (1024 * 1024);
    uart_puts("OISC setup: DRAM = ");
    uart_puthex(mb);
    uart_puts(" MiB, cpu_relax ready\r\n");
}

/*
 * oisc_init_irq: OISC has a single interrupt-mask word and no devices to
 * wire up yet; keep the mask clear (all interrupts enabled is a no-op here).
 */
void oisc_init_irq(void)
{
    u32 m;
    m = 0;
    (void)m;
}