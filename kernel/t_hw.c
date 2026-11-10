#include <asm/types.h>
#include <asm/oisc_hw.h>

u32 g_page;
u32 g_mask;
int g_flags;
u32 g_timer;
int g;

int main()
{
    g_page = PAGE_SIZE;
    g_mask = PAGE_MASK;
    g_flags = OISC_FLAGS;
    g_timer = OISC_TIMER_COMPARE;
    g = g_page + g_flags + g_timer + (OISC_UART_TX - OISC_UART_BASE);
    return 0;
}