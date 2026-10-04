/* engine32c/engine.h — addresses/layouts in the PRISTINE iw4x.exe (image base 0x400000) that the
 * injected code uses. Relocated arrays are reached through engine pointers that patch_engine.py
 * already rewrote (e.g. level.clients), never through their old static addresses. */
#ifndef ENGINE32C_ENGINE_H
#define ENGINE32C_ENGINE_H

typedef float vec3_t[3];


/* functions (all cdecl in the original) */
typedef void (__cdecl *Com_Printf_t)(int channel, const char *fmt, ...);
#define Com_Printf            ((Com_Printf_t)0x402500)

/* no CRT: our own memset (GCC may also emit calls to `memset` for struct zeroing) */
void *e32_memset(void *dst, int c, unsigned int n);
void *memset(void *dst, int c, unsigned int n);

#endif
