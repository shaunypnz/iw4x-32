/*
 * engine32c/antilag.c — 32-client re-implementation of MW2's server-side lag compensation.
 *
 * Original (pristine iw4x.exe) call chain, all sized for MAX_CLIENTS = 18:
 *   G_AntiLagRewindClientPos  0x4C1120 (int time, AntilagClientStore *store)
 *     -> AntiLag_GetArchivedPositions 0x455960 (time, vec3 pos[18], vec3 ang[18], bool valid[18])
 *          -> SV archive frame lookup 0x4DC220 (int *msecAgo) -> frame*
 *          -> decode frame 0x629340 (frame, pos[18], ang[18], valid[18])   [stops at clientNum >= 18]
 *   G_AntiLagRestoreClientPos 0x440040 (AntilagClientStore *store)
 * AntilagClientStore (0x1C4) = { vec3 pos[18]; vec3 ang[18]; bool moved[18]; } lives in the
 * CALLER's stack frame (3 callers, each only passes it from rewind to restore). With 32 slots
 * the rewind loop wrote moved[18..31] over the caller's return address.
 *
 * This file replaces rewind + restore (hooked at their entry points by patch_engine.py P6).
 * The caller's store pointer is ignored; a single global 32-entry store is used instead
 * (rewind/restore are never nested). The cached-client ring the archive decoder reads already
 * holds every client; only the decoder's 18 cut-off and the 18-entry buffers are widened.
 * Logic is a line-by-line transcription of the disassembly; only the bounds changed.
 */
#include "engine.h"

#define AL_MAX 32

typedef struct {
    vec3_t pos[AL_MAX];
    vec3_t ang[AL_MAX];
    unsigned char moved[AL_MAX];
} AntilagStore32;

static AntilagStore32 g_alStore;

/* diagnostics, readable from outside via /proc/<pid>/mem (addresses in build/engine32c.map) */
volatile unsigned int e32_stat_rewinds;        /* calls to e32_AntiLagRewind            */
volatile unsigned int e32_stat_rewound_hi;     /* clients >= 18 actually rewound         */
volatile unsigned int e32_stat_restores;       /* calls to e32_AntiLagRestore           */

/* decode one archived frame (0x629340, 32-client bound) */
static void e32_DecodeArchiveFrame(const archivedFrame_t *frame, vec3_t *pos, vec3_t *ang,
                                   unsigned char *valid)
{
    for (unsigned int k = 0; k < frame->numClients; ++k) {
        const cachedClient_t *cc = &CACHED_CLIENTS[(frame->firstClient + k) % CACHED_CLIENTS_NUM];
        int cn = cc->clientNum;
        if (cn >= AL_MAX)
            break;                                  /* entries are sorted by clientNum */
        valid[cn] = 1;
        BG_EvaluateTrajectory(&cc->pos, frame->time, pos[cn]);
        ang[cn][0] = 0.0f;
        ang[cn][1] = cc->yaw;
        ang[cn][2] = 0.0f;
    }
}

/* 0x455960 with 32-entry buffers */
static int e32_GetArchivedPositions(int time, vec3_t *pos, vec3_t *ang, unsigned char *valid)
{
    static vec3_t posOld[AL_MAX], angOld[AL_MAX], posNew[AL_MAX], angNew[AL_MAX];
    unsigned char validOld[AL_MAX], validNew[AL_MAX];
    int delta = SVS_TIME - time;
    int n = delta / 50;
    int msOld = (n + 2) * 50;      /* [S+0x14] — passed by pointer, lookup may clamp it */
    int msNew = (n + 1) * 50;      /* [S+0x18] */
    int trOld = msOld;             /* [S+0x1C] copy — step counter for the older walk */
    int trNew = msNew;             /* ebp      — step counter for the newer walk */

    archivedFrame_t *fOld = SV_GetArchivedFrame(&msOld);
    archivedFrame_t *fNew = SV_GetArchivedFrame(&msNew);
    if (!fOld && !fNew) {
        Com_Printf(15, "Failed to get a cached snapshot for antilag - offset is %i\n", delta);
        return 0;
    }
    /* 0x4559E4: newer frame — step forward until it is at/after the target time */
    while (fNew && fNew->time < time) {
        trNew -= 50;
        fOld = fNew;
        msNew = trNew;
        fNew = SV_GetArchivedFrame(&msNew);
    }
    /* 0x455A20: older frame — step back while it is still after the target time */
    while (fOld && fOld->time > time) {
        trOld += 50;
        msOld = trOld;
        fOld = SV_GetArchivedFrame(&msOld);
    }
    int haveOld = fOld != 0, haveNew = fNew != 0;
    e32_memset(validOld, 0, sizeof validOld);
    e32_memset(validNew, 0, sizeof validNew);
    if (haveOld)
        e32_DecodeArchiveFrame(fOld, posOld, angOld, validOld);
    if (haveNew)
        e32_DecodeArchiveFrame(fNew, posNew, angNew, validNew);

    float frac = 0.0f;
    if (haveOld && haveNew && msOld != msNew && fNew->time != fOld->time)   /* last test: div-by-0 guard (not in original) */
        frac = (float)(time - fOld->time) / (float)(fNew->time - fOld->time);

    for (int i = 0; i < AL_MAX; ++i) {
        if (validOld[i] && validNew[i]) {
            valid[i] = 1;
            for (int c = 0; c < 3; ++c) {
                pos[i][c] = posOld[i][c] + frac * (posNew[i][c] - posOld[i][c]);
                ang[i][c] = angOld[i][c] + frac * (angNew[i][c] - angOld[i][c]);
            }
        } else if (validOld[i]) {
            valid[i] = 1;
            for (int c = 0; c < 3; ++c) { pos[i][c] = posOld[i][c]; ang[i][c] = angOld[i][c]; }
        } else if (validNew[i]) {
            valid[i] = 1;
            for (int c = 0; c < 3; ++c) { pos[i][c] = posNew[i][c]; ang[i][c] = angNew[i][c]; }
        }
    }
    return 1;
}

/* hook target for 0x4C1120 */
void __cdecl e32_AntiLagRewind(int time, void *callerStore)
{
    static vec3_t pos[AL_MAX], ang[AL_MAX];
    unsigned char valid[AL_MAX];
    (void)callerStore;
    ++e32_stat_rewinds;

    e32_memset(&g_alStore, 0, sizeof g_alStore);
    if (LEVEL_TIME - time > 400)
        time = LEVEL_TIME - 400;
    e32_memset(valid, 0, sizeof valid);
    if (!e32_GetArchivedPositions(time, pos, ang, valid))
        return;

    int maxc = LEVEL_MAXCLIENTS;
    if (maxc > AL_MAX)
        maxc = AL_MAX;
    for (int i = 0; i < maxc; ++i) {
        char *gc = LEVEL_CLIENTS + i * GCLIENT_SIZE;
        if (valid[i] && *(int *)(gc + GCLIENT_SESS_CONNECTED) == 2 && *(int *)(gc + GCLIENT_0x311C) == 0) {
            char *ent = G_ENTITIES + i * GENTITY_SIZE;
            float *org = (float *)(ent + GENT_CURRENT_ORIGIN);
            float *angs = (float *)(ent + GENT_CURRENT_ANGLES);
            for (int c = 0; c < 3; ++c) {
                g_alStore.pos[i][c] = org[c];
                g_alStore.ang[i][c] = angs[c];
            }
            for (int c = 0; c < 3; ++c) {
                org[c] = pos[i][c];
                angs[c] = ang[i][c];
            }
            SV_LinkEntity(ent);
            g_alStore.moved[i] = 1;
            if (i >= 18)
                ++e32_stat_rewound_hi;
        } else {
            g_alStore.moved[i] = 0;
        }
    }
}

/* hook target for 0x440040 */
void __cdecl e32_AntiLagRestore(void *callerStore)
{
    (void)callerStore;
    ++e32_stat_restores;
    int maxc = LEVEL_MAXCLIENTS;
    if (maxc > AL_MAX)
        maxc = AL_MAX;
    for (int i = 0; i < maxc; ++i) {
        if (!g_alStore.moved[i])
            continue;
        char *ent = G_ENTITIES + i * GENTITY_SIZE;
        float *org = (float *)(ent + GENT_CURRENT_ORIGIN);
        float *angs = (float *)(ent + GENT_CURRENT_ANGLES);
        for (int c = 0; c < 3; ++c) {
            org[c] = g_alStore.pos[i][c];
            angs[c] = g_alStore.ang[i][c];
        }
        SV_LinkEntity(ent);
        g_alStore.moved[i] = 0;
    }
}
