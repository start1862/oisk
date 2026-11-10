#include <asm/types.h>
#include <asm/cache.h>
#include <asm/cacheflush.h>

int g_l1;
int g_done;

int main()
{
    g_l1 = L1_CACHE_BYTES;
    flush_dcache_all();
    local_dcache_page_flush(0);
    flush_cache_all();
    sync_icache_dcache(0);
    g_done = 1;
    return 0;
}