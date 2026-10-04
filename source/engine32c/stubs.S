/*
 * engine32c/stubs.S — hand-written hook stubs injected into iw4x.exe (section .iw4c @ 0x8800000).
 * Each stub replaces >=5 bytes at a hook site (patch_engine.py P6 writes `jmp stub` there)
 * and jumps back. Keep stack effect and flags identical to the original instructions.
 */
        .intel_syntax noprefix
        .text


/* ---- r17: session / party tables hold 18 clients ------------------------------------------
 * SessionData.users[18] (0x38 each, at session+0x230) and the lobby's partyMembers[18] (0xE0) are
 * indexed by client slot with no bound. Only REAL players register (bots don't), so a human in
 * slot 18+ overwrote the session's own control fields and, from slot 23, the next session object;
 * dropping them tore down lobby member 31 -> server death (c19). Clients 18+ are kept out of the
 * party/session bookkeeping entirely (IW4x's own GUID/auth, name, rate etc. are unaffected). */


/* G3 hook 0x487C10 Session_GetXuidForSlot(session, slot): `mov eax,[esp+8]; mov edx,[esp+4]`
 * (8 bytes). slot >= 18 -> xuid 0 ("not registered") instead of reading past users[]. */
        .globl  _e32_xuid_for_slot
_e32_xuid_for_slot:
        mov     eax, dword ptr [esp + 8]
        cmp     eax, 0x12
        jae     1f
        mov     edx, dword ptr [esp + 4]
        jmp     0x487C18
1:      xor     eax, eax
        xor     edx, edx
        ret

/* G4 hook 0x49ABB0 Session_SetClientAddress(session, slot, ...): `sub esp,0x14; push esi;
 * mov esi,[esp+0x1C]` (8 bytes). slot >= 18 -> return (callers ignore the result). */
        .globl  _e32_set_addr
_e32_set_addr:
        cmp     dword ptr [esp + 8], 0x12
        jae     1f
        sub     esp, 0x14
        push    esi
        mov     esi, dword ptr [esp + 0x1C]
        jmp     0x49ABB8
1:      ret

/* G5 hook 0x4D3D00 PartyHost member teardown(party, slot, ...): `sub esp,0x28; push ebx; push ebp`
 * (5 bytes). members[] holds 18 (0xE0 each) -> slot >= 18 -> return (callers ignore the result). */
        .globl  _e32_member_teardown
_e32_member_teardown:
        cmp     dword ptr [esp + 8], 0x12
        jae     1f
        sub     esp, 0x28
        push    ebx
        push    ebp
        jmp     0x4D3D05
1:      ret



/* ---- compat (compat.c): one patched client for stock and 32-player servers ------------------------ */

/* C1 hook 0x4261B5 (SV_SpawnServer -> server dvar registration, right after sv_maxclients):
 * `mov [0x2098D90],eax` (5 bytes) -> register "iw4x32" and force our 32-player layout. */
        .globl  _e32_marker_hook
_e32_marker_hook:
        mov     dword ptr ds:[0x2098D90], eax
        pushad
        push    eax                     /* the sv_maxclients dvar */
        call    _e32_server_spawn
        add     esp, 4
        popad
        jmp     0x4261BA

/* C4 hook 0x4D9571 CL_Init: `push 0x724230` (5 bytes) -> register "iw4x32" (userinfo) on the client. */
        .globl  _e32_cl_init_hook
_e32_cl_init_hook:
        pushad
        call    _e32_register_marker
        popad
        push    0x724230
        jmp     0x4D9576


/* C3 hook 0x4CCF44 CG_ParseServerinfo: `push 0x6FB5B0` (5 bytes); esi = CS_SERVERINFO string. */
        .globl  _e32_cg_si_hook
_e32_cg_si_hook:
        pushad
        push    esi
        call    _e32_cg_serverinfo
        add     esp, 4
        popad
        push    0x6FB5B0
        jmp     0x4CCF49

