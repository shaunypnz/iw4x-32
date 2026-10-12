/*
 * IW4x-32 loader — applies the 32-player patches to the UNMODIFIED IW4x r5121 iw4x.exe and
 * iw4x.dll in memory, from DllMain of a binkw32.dll proxy (every Bink export is forwarded to the
 * renamed original, binkw32_orig.dll — see binkw32.def).
 *
 * Why this works: the process loader maps and initialises every imported DLL before the game's
 * entry point runs, and IW4x installs its own hooks only when that entry point runs. So the bytes
 * written here are in place before any game or IW4x code executes — the same end state as the
 * patched files produced by patch_engine.py / patch_dll.py (tables.h is diffed from those files).
 *
 * The engine's two added blocks (32-player data arrays, injected C code) go wherever the OS places
 * them; every patched slot that refers to them is fixed up (see gen_tables.py for how they are found).
 *
 * Fail-safe: if either file is not the exact version the tables were built for, if any byte to be
 * replaced is not what we expect, or if memory cannot be allocated, NOTHING is written and the game runs as stock 18-player IW4x. Every decision is logged to
 * iw4x32-loader.log in the game folder. Creating a file named iw4x32-disable in the game folder
 * turns the loader off.
 */
#include <windows.h>
#include <wincrypt.h>
#include <string.h>

#include "tables.h"

#define LOG_NAME "iw4x32-loader.log"
#define DISABLE_NAME "iw4x32-disable"

static char g_dir[MAX_PATH];

static void llog(const char *fmt, ...)
{
    char buf[1024], path[MAX_PATH];
    va_list ap;
    va_start(ap, fmt);
    int n = wvsprintfA(buf, fmt, ap);
    va_end(ap);
    if (n < 0)
        return;
    buf[n++] = '\r';
    buf[n++] = '\n';
    lstrcpyA(path, g_dir);
    lstrcatA(path, LOG_NAME);
    HANDLE h = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    DWORD w;
    WriteFile(h, buf, (DWORD)n, &w, NULL);
    CloseHandle(h);
}

static int md5_file(const char *path, char out[33])
{
    int ok = 0;
    HCRYPTPROV prov = 0;
    HCRYPTHASH hash = 0;
    HANDLE f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE)
        return 0;
    if (CryptAcquireContextA(&prov, NULL, NULL, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT) &&
        CryptCreateHash(prov, CALG_MD5, 0, 0, &hash)) {
        static BYTE buf[1 << 16];
        DWORD got;
        ok = 1;
        while (ReadFile(f, buf, sizeof buf, &got, NULL) && got)
            if (!CryptHashData(hash, buf, got, 0)) { ok = 0; break; }
        if (ok) {
            BYTE dig[16];
            DWORD len = 16;
            if (CryptGetHashParam(hash, HP_HASHVAL, dig, &len, 0) && len == 16) {
                static const char hx[] = "0123456789abcdef";
                for (int i = 0; i < 16; i++) { out[2 * i] = hx[dig[i] >> 4]; out[2 * i + 1] = hx[dig[i] & 15]; }
                out[32] = 0;
            } else
                ok = 0;
        }
    }
    if (hash) CryptDestroyHash(hash);
    if (prov) CryptReleaseContext(prov, 0);
    CloseHandle(f);
    return ok;
}

static int write_mem(void *dst, const void *src, SIZE_T n)
{
    DWORD old;
    if (!VirtualProtect(dst, n, PAGE_EXECUTE_READWRITE, &old))
        return 0;
    memcpy(dst, src, n);
    VirtualProtect(dst, n, old, &old);
    return 1;
}

static int g_data_delta, g_code_delta;     /* allocation - address the tables were built for */

static void apply_fix(unsigned char *p, unsigned kind)
{
    unsigned v;
    memcpy(&v, p, 4);
    v += (unsigned)(((int)(kind % 3) - 1) * g_data_delta + ((int)(kind / 3) - 1) * g_code_delta);
    memcpy(p, &v, 4);
}

/* in-memory original bytes of a DLL run: file bytes + delta on slots the original .reloc rebases */
static void dll_expected_old(const dll_run_t *r, unsigned delta, unsigned char *out)
{
    memcpy(out, dll_old + r->off, r->len);
    for (int k = 0; k < r->nold; k++) {
        unsigned o = dll_slots[r->slot + k], v;
        memcpy(&v, out + o, 4);
        v += delta;
        memcpy(out + o, &v, 4);
    }
}

/* new bytes of a DLL run: slots the patched .reloc rebases point either into the image (+delta) or
 * into the appended zero-fill section (our own allocation); engine-pointer slots point into the
 * engine's relocated data block */
static void dll_new_bytes(const dll_run_t *r, unsigned delta, unsigned char *newsec, unsigned char *out)
{
    memcpy(out, dll_new + r->off, r->len);
    for (int k = 0; k < r->nnew; k++) {
        unsigned o = dll_slots[r->slot + r->nold + k], v;
        memcpy(&v, out + o, 4);
        if (v >= DLL_PREF_BASE + DLL_NEWSEC_RVA && v < DLL_PREF_BASE + DLL_NEWSEC_RVA + DLL_NEWSEC_SIZE)
            v = (unsigned)(UINT_PTR)newsec + (v - (DLL_PREF_BASE + DLL_NEWSEC_RVA));
        else
            v += delta;
        memcpy(out + o, &v, 4);
    }
    for (int k = 0; k < r->neng; k++)
        apply_fix(out + dll_slots[r->slot + r->nold + r->nnew + k], 5);   /* +data_delta */
}

static void apply(void)
{
    char path[MAX_PATH], sum[33];
    unsigned char tmp[512];

    lstrcpyA(path, g_dir);
    lstrcatA(path, DISABLE_NAME);
    if (GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES) {
        llog("disabled by %s - running stock IW4x", DISABLE_NAME);
        return;
    }

    /* 1. versions */
    if (!GetModuleFileNameA(NULL, path, MAX_PATH) || !md5_file(path, sum)) {
        llog("cannot hash the game exe - not patching");
        return;
    }
    if (lstrcmpiA(sum, EXE_ORIG_MD5)) {
        llog("iw4x.exe md5 %s, need %s (IW4x r5121) - not patching", sum, EXE_ORIG_MD5);
        return;
    }
    HMODULE dll = GetModuleHandleA("iw4x.dll");
    if (!dll || !GetModuleFileNameA(dll, path, MAX_PATH) || !md5_file(path, sum)) {
        llog("iw4x.dll not loaded or unreadable - not patching");
        return;
    }
    if (lstrcmpiA(sum, DLL_ORIG_MD5)) {
        llog("iw4x.dll md5 %s, need %s (IW4x r5121) - not patching (IW4x updated? a new loader build is needed)", sum, DLL_ORIG_MD5);
        return;
    }
    unsigned dbase = (unsigned)(UINT_PTR)dll, delta = dbase - DLL_PREF_BASE;

    /* 2. verify every byte we are going to replace */
    for (int i = 0; i < EXE_NRUNS; i++) {
        const exe_run_t *r = &exe_runs[i];
        if (memcmp((void *)(UINT_PTR)r->va, exe_old + r->off, r->len)) {
            llog("iw4x.exe bytes at %08X differ from r5121 (already patched, or hooked by something else) - not patching", r->va);
            return;
        }
    }
    for (int i = 0; i < DLL_NRUNS; i++) {
        const dll_run_t *r = &dll_runs[i];
        if (r->len > sizeof tmp) {
            llog("internal: dll run too long");
            return;
        }
        dll_expected_old(r, delta, tmp);
        if (memcmp((void *)(UINT_PTR)(dbase + r->rva), tmp, r->len)) {
            llog("iw4x.dll bytes at rva %08X differ from r5121 - not patching", r->rva);
            return;
        }
    }

    /* 3. memory: anywhere the OS likes */
    unsigned char *data = VirtualAlloc(NULL, DATA_SIZE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    unsigned char *code = VirtualAlloc(NULL, CODE_SIZE, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
    unsigned char *newsec = VirtualAlloc(NULL, DLL_NEWSEC_SIZE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!data || !code || !newsec) {
        llog("cannot allocate memory (%08X/%08X/%08X bytes, error %lu) - not patching",
             DATA_SIZE, CODE_SIZE, DLL_NEWSEC_SIZE, GetLastError());
        if (data) VirtualFree(data, 0, MEM_RELEASE);
        if (code) VirtualFree(code, 0, MEM_RELEASE);
        if (newsec) VirtualFree(newsec, 0, MEM_RELEASE);
        return;
    }
    g_data_delta = (int)((UINT_PTR)data - DATA_VA);
    g_code_delta = (int)((UINT_PTR)code - CODE_VA);

    /* 4. write: injected code (relocated), then the engine, then the DLL */
    memcpy(code, code_raw, CODE_RAWLEN);
    for (int i = 0; i < CODE_NFIX; i++)
        apply_fix(code + code_fix[i].off, code_fix[i].kind);
    for (int i = 0; i < EXE_NRUNS; i++) {
        const exe_run_t *r = &exe_runs[i];
        unsigned char *buf = r->len <= sizeof tmp ? tmp : HeapAlloc(GetProcessHeap(), 0, r->len);
        if (!buf)
            continue;
        memcpy(buf, exe_new + r->off, r->len);
        for (int k = 0; k < r->nfix; k++)
            apply_fix(buf + exe_fix[r->fix + k].off, exe_fix[r->fix + k].kind);
        write_mem((void *)(UINT_PTR)r->va, buf, r->len);
        if (buf != tmp)
            HeapFree(GetProcessHeap(), 0, buf);
    }
    for (int i = 0; i < DLL_NRUNS; i++) {
        dll_new_bytes(&dll_runs[i], delta, newsec, tmp);
        write_mem((void *)(UINT_PTR)(dbase + dll_runs[i].rva), tmp, dll_runs[i].len);
    }
    FlushInstructionCache(GetCurrentProcess(), NULL, 0);
    llog("patched: iw4x.exe %d runs, iw4x.dll %d runs; engine data at %08X, code at %08X, dll arrays at %08X, "
         "dll base %08X - 32 players enabled [%s + %s]",
         EXE_NRUNS, DLL_NRUNS, (unsigned)(UINT_PTR)data, (unsigned)(UINT_PTR)code, (unsigned)(UINT_PTR)newsec,
         dbase, EXE_SRC, DLL_SRC);
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(inst);
        DWORD n = GetModuleFileNameA(NULL, g_dir, MAX_PATH);
        while (n && g_dir[n - 1] != '\\' && g_dir[n - 1] != '/')
            n--;
        g_dir[n] = 0;
        apply();
    }
    return TRUE;
}
