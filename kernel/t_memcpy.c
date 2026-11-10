#include <asm/types.h>

/* prototype matching arch/oisc/lib/memcpy.c */
void oisc_memcpy_words(unsigned long *dst, unsigned long *src,
                       unsigned long nwords);

int g_src[4];
int g_dst[4];
int g_sum;

int main()
{
    unsigned long *d;
    unsigned long *s;

    g_src[0] = 1;
    g_src[1] = 2;
    g_src[2] = 3;
    g_src[3] = 4;
    g_dst[0] = 0;
    g_dst[1] = 0;
    g_dst[2] = 0;
    g_dst[3] = 0;

    d = (unsigned long *)g_dst;
    s = (unsigned long *)g_src;
    oisc_memcpy_words(d, s, 4);

    g_sum = g_dst[0] + g_dst[1] + g_dst[2] + g_dst[3];
    return 0;
}