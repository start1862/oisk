/*
 * arch/oisc/lib/delay.c
 *
 * OISC delay loops (rewritten for OSCC: no 64-bit arithmetic, no
 * volatile, no kernel-internal headers beyond the asm/ subset).
 *
 * The machine has a free-running 32-bit cycle counter; __delay spins
 * until (get_cycles() - start) wraps past the requested cycles, which
 * is valid for any delay < 2^31.
 */
#include <asm/types.h>
#include <asm/oisc_hw.h>
#include <asm/timex.h>
#include <asm/delay.h>

unsigned long loops_per_jiffy = 1000000;
u32 jiffies_hz = 100;

int read_current_timer(unsigned long *timer_value)
{
    *timer_value = get_cycles();
    return 0;
}

void __delay(unsigned long cycles)
{
    unsigned long start;
    unsigned long now;

    start = get_cycles();
    for (;;) {
        now = get_cycles();
        if ((now - start) >= cycles)
            break;
        cpu_relax();
    }
}

void __udelay(unsigned long usecs)
{
    /* cycles per usec = loops_per_jiffy / (jiffies_hz * 1000) */
    unsigned long c;
    unsigned long den;

    den = jiffies_hz * 1000;
    if (den == 0)
        return;
    c = (loops_per_jiffy * usecs) / den;
    __delay(c);
}

void __ndelay(unsigned long nsecs)
{
    /* cycles per nsec = loops_per_jiffy / (jiffies_hz * 1000000) */
    unsigned long c;
    unsigned long den;

    den = jiffies_hz * 1000000;
    if (den == 0)
        return;
    c = (loops_per_jiffy * nsecs) / den;
    __delay(c);
}