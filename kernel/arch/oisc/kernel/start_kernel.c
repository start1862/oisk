/*
 * arch/oisc/kernel/start_kernel.c (minimal)
 *
 * The very first "kernel" milestone for the OISC port: a single entry
 * point that brings up setup_arch() and prints a deterministic boot log
 * through the MMIO UART, then parks in an infinite idle loop.
 *
 * This is deliberately the smallest thing that exercises the real boot
 * path shape: setup_arch -> banner -> unreadable-from-C idle.  It is a
 * stepping stone toward the full start_kernel(); memory management,
 * scheduling and drivers come in later milestones.
 */
#include <asm/types.h>
#include <asm/oisc_hw.h>
#include <asm/uart.h>
#include <asm/timex.h>

/* provided by arch/oisc/kernel/setup.c (merged into this TU) */
void oisc_setup_arch(void);

/* ---- tiny kprintf stand-in: string + newline ---- */
void kput(const char *s)
{
    uart_puts(s);
    uart_putnl();
}

static void print_banner(void)
{
    kput("OISC-Linux 0.0.1");
    kput("");
    kput("Linux is running on a SUBLEQ machine.");
}

void kernel_entry(void)
{
    oisc_setup_arch();

    print_banner();

    uart_puts("Booting the simulated OISC machine...\r\n");
    uart_puts("Kernel alive. Halting via idle loop (never reached).\r\n");

    /* idle loop: OISC has no wfi; spin on cpu_relax forever */
    while (1) {
        cpu_relax();
    }
}