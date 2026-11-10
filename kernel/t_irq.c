#include <asm/types.h>
#include <asm/irq.h>

int g1;
int g2;
int g3;

int main()
{
    *(u32 *)OISC_IRQ_MASK = 0;
    g1 = arch_local_save_flags();

    arch_local_irq_enable();
    g2 = arch_local_save_flags();

    arch_local_irq_disable();
    g3 = arch_local_save_flags();

    return 0;
}