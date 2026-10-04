/* engine32c/compat.c — one patched client for BOTH stock 18-player IW4x servers and our 32-player servers,
 * and a 32-player server that only admits patched clients.
 *
 *  - Marker dvar "iw4x32" (bool 1, USERINFO|SERVERINFO|ROM) is registered in CL_Init and in SV_SpawnServer.
 *    Patched clients therefore send iw4x32\1 in their userinfo, and a server running our exe advertises
 *    iw4x32\1 in its serverinfo (CS_SERVERINFO). Starting a server (incl. a private match hosted by a
 *    patched client) also forces our 32-player layout back on.
 *  - Server: SV_DirectConnect rejects remote clients whose userinfo lacks iw4x32\1 (bots/loopback pass).
 *  - Client: CG_ParseServerinfo -> e32_cg_serverinfo(): if the server does not advertise iw4x32, the
 *    layout-dependent code sites (players vs dead bodies by entity number, corpse index base) are written
 *    back to their stock bytes; when it does, our bytes are restored. Stock servers put body clones at
 *    entities 18..25, our layout at 36..43 (crash c50: corpse index entnum-36 on a stock server).
 *    The site table is filled into this blob by patch_engine.py (DUAL_SITES). */
#include "engine.h"

typedef const char *(__cdecl *Info_ValueForKey_t)(const char *s, const char *key);
typedef void *(__cdecl *Dvar_RegisterBool_t)(const char *name, int value, unsigned int flags, const char *desc);
typedef void (__cdecl *Dvar_SetBool_t)(void *dvar, int value);
typedef void *(__stdcall *GetModuleHandleA_t)(const char *name);
typedef void *(__stdcall *GetProcAddress_t)(void *module, const char *name);
typedef int (__stdcall *VirtualProtect_t)(void *addr, unsigned int size, unsigned int prot, unsigned int *old);
#define Info_ValueForKey   ((Info_ValueForKey_t)0x47C820)
#define Dvar_RegisterBool  ((Dvar_RegisterBool_t)0x4CE1A0)
#define Dvar_SetBool       ((Dvar_SetBool_t)0x4A9510)
#define DVAR_CURRENT_INT(d) (*(volatile int *)((char *)(d) + 0x10))
#define pGetModuleHandleA  (*(GetModuleHandleA_t *)0x6D71FC)   /* KERNEL32 IAT */
#define pGetProcAddress    (*(GetProcAddress_t *)0x6D7210)

#define DVAR_USERINFO   0x200
#define DVAR_SERVERINFO 0x400
#define DVAR_ROM        0x2000
#define NA_BOT          0
#define NA_LOOPBACK     2

#define E32_DUAL_MAX   96
#define E32_DUAL_BYTES 12
typedef struct {
    unsigned int va;                       /* 0 terminates */
    unsigned int len;                      /* <= E32_DUAL_BYTES */
    unsigned char stock[E32_DUAL_BYTES];   /* original bytes (stock 18-player layout) */
} e32_dual_t;

/* initialised (not .bss) so patch_engine.py can fill it inside the blob; the first va is a placeholder */
e32_dual_t e32_dual_tab[E32_DUAL_MAX] = { { 0xE32D0A1u, 0, { 0 } } };
static unsigned char e32_dual_ours[E32_DUAL_MAX][E32_DUAL_BYTES];
static int e32_captured;
static int e32_layout32 = 1;               /* the image starts with our (32-player) bytes */
static int e32_server_is32 = 1;            /* this process hosts a server with > 18 slots */

static int e32_streq(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

static void e32_copy(volatile unsigned char *dst, const unsigned char *src, unsigned int n)
{
    while (n--)
        *dst++ = *src++;
}

void __cdecl e32_register_marker(void)
{
    Dvar_RegisterBool("iw4x32", 1, DVAR_USERINFO | DVAR_ROM, "IW4x 32-player build: patched clients send it");
}

static void e32_set_layout(int is32);

/* SV_SpawnServer (hook passes the freshly registered sv_maxclients dvar):
 *   > 18 slots: our 32-player layout, only patched clients admitted, serverinfo sv_iw4x32 = 1;
 *  <= 18 slots: COMPATIBILITY mode — stock layout (bodies 18..25, first free entity 26), every client admitted
 *               (unpatched ones too), sv_iw4x32 = 0 so patched clients also use the stock layout. */
void __cdecl e32_server_spawn(void *maxclientsDvar)
{
    int maxc = maxclientsDvar ? DVAR_CURRENT_INT(maxclientsDvar) : 32;
    void *d;
    e32_register_marker();
    e32_server_is32 = 0;                   /* public player build: never a 32-player host (stock server layout) */
    d = Dvar_RegisterBool("sv_iw4x32", e32_server_is32, DVAR_SERVERINFO | DVAR_ROM,
                          "IW4x 32-player server: 1 = 32-player layout (patched clients only), 0 = stock layout");
    if (d)
        Dvar_SetBool(d, e32_server_is32);
    e32_set_layout(e32_server_is32);
    Com_Printf(16, "iw4x32: %d-slot server - %s\n", maxc,
               e32_server_is32 ? "32-player layout, patched clients only" : "stock layout, all clients can join");
}


static void e32_set_layout(int is32)
{
    static VirtualProtect_t vp;
    unsigned int i, old;
    if (is32 == e32_layout32)
        return;
    if (!vp) {
        void *k32 = pGetModuleHandleA("kernel32.dll");
        vp = k32 ? (VirtualProtect_t)pGetProcAddress(k32, "VirtualProtect") : 0;
        if (!vp) {
            Com_Printf(16, "iw4x32: VirtualProtect not found - cannot switch layout\n");
            return;
        }
    }
    if (!e32_captured) {                   /* our bytes, as present in memory (patched exe or loader) */
        for (i = 0; i < E32_DUAL_MAX && e32_dual_tab[i].va && e32_dual_tab[i].len; i++)
            e32_copy(e32_dual_ours[i], (const unsigned char *)e32_dual_tab[i].va, e32_dual_tab[i].len);
        e32_captured = 1;
    }
    for (i = 0; i < E32_DUAL_MAX && e32_dual_tab[i].va && e32_dual_tab[i].len; i++) {
        void *p = (void *)e32_dual_tab[i].va;
        if (!vp(p, e32_dual_tab[i].len, 0x40 /* PAGE_EXECUTE_READWRITE */, &old))
            continue;
        e32_copy((volatile unsigned char *)p, is32 ? e32_dual_ours[i] : e32_dual_tab[i].stock, e32_dual_tab[i].len);
        vp(p, e32_dual_tab[i].len, old, &old);
    }
    e32_layout32 = is32;
    Com_Printf(16, "iw4x32: %s server - using the %s player/body layout (%u sites)\n",
               is32 ? "32-player" : "stock", is32 ? "32-player" : "stock 18-player", i);
}

/* CG_ParseServerinfo (hook): info = CS_SERVERINFO string */
void __cdecl e32_cg_serverinfo(const char *info)
{
    const char *v = Info_ValueForKey(info, "sv_iw4x32");
    e32_set_layout(v && e32_streq(v, "1"));
}
