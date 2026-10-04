/* engine32c/util.c — freestanding helpers */
#include "engine.h"

void *e32_memset(void *dst, int c, unsigned int n)
{
    volatile unsigned char *p = (volatile unsigned char *)dst;   /* volatile: stop GCC turning this loop into a memset call */
    while (n--)
        *p++ = (unsigned char)c;
    return dst;
}

void *memset(void *dst, int c, unsigned int n)
{
    return e32_memset(dst, c, n);
}
