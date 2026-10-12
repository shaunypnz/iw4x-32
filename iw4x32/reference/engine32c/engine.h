/* engine32c/engine.h — addresses/layouts in the PRISTINE iw4x.exe (image base 0x400000) that the
 * injected code uses. Relocated arrays are reached through engine pointers that patch_engine.py
 * already rewrote (e.g. level.clients), never through their old static addresses. */
#ifndef ENGINE32C_ENGINE_H
#define ENGINE32C_ENGINE_H

typedef float vec3_t[3];

#ifndef E32_CLIENT   /* anti-lag (server build only) */
/* globals */
#define SVS_TIME          (*(volatile int *)0x31D9384)
#define LEVEL_CLIENTS     (*(char *volatile *)0x1A831A8)   /* level.clients -> relocated g_clients */
#define LEVEL_MAXCLIENTS  (*(volatile int *)0x1A8354C)
#define LEVEL_TIME        (*(volatile int *)0x1A83554)
#define G_ENTITIES        ((char *)0x18835D8)

/* struct layouts */
#define GCLIENT_SIZE           0x366C
#define GCLIENT_SESS_CONNECTED 0x3148   /* == 2 (CON_CONNECTED) */
#define GCLIENT_0x311C         0x311C   /* must be 0 for anti-lag (as in original) */
#define GENTITY_SIZE           0x274
#define GENT_CURRENT_ORIGIN    0x138    /* entityShared_t.currentOrigin */
#define GENT_CURRENT_ANGLES    0x144    /* entityShared_t.currentAngles */

/* server client-state cache used by the snapshot archive */
typedef struct {
    int clientNum;                      /* +0x00 */
    int _pad04[2];
    unsigned char pos[0x34];            /* +0x0C trajectory_t (opaque; BG_EvaluateTrajectory) */
    float yaw;                          /* +0x40 */
    unsigned char _rest[0x11C - 0x44];
} cachedClient_t;
#define CACHED_CLIENTS     ((const cachedClient_t *)0x209C600)
#define CACHED_CLIENTS_NUM 0x2A30

typedef struct {
    int _unk00;
    int time;                           /* +0x04 */
    unsigned int numClients;            /* +0x08 */
    unsigned int firstClient;           /* +0x0C index into CACHED_CLIENTS ring */
} archivedFrame_t;

#endif

/* functions (all cdecl in the original) */
typedef void (__cdecl *Com_Printf_t)(int channel, const char *fmt, ...);
#define Com_Printf            ((Com_Printf_t)0x402500)
#ifndef E32_CLIENT
typedef archivedFrame_t *(__cdecl *SV_GetArchivedFrame_t)(int *msecAgo);
typedef void (__cdecl *BG_EvaluateTrajectory_t)(const void *tr, int atTime, float *result);
typedef void (__cdecl *SV_LinkEntity_t)(void *ent);
#define SV_GetArchivedFrame   ((SV_GetArchivedFrame_t)0x4DC220)
#define BG_EvaluateTrajectory ((BG_EvaluateTrajectory_t)0x45C170)
#define SV_LinkEntity         ((SV_LinkEntity_t)0x4E0880)
#endif

/* no CRT: our own memset (GCC may also emit calls to `memset` for struct zeroing) */
void *e32_memset(void *dst, int c, unsigned int n);
void *memset(void *dst, int c, unsigned int n);

#ifndef E32_CLIENT
_Static_assert(sizeof(cachedClient_t) == 0x11C, "cachedClient_t size");
#endif
#endif
