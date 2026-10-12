/*
 * engine32c/stubs.S — hand-written hook stubs injected into iw4x.exe (section .iw4c @ 0x8800000).
 * Each stub replaces >=5 bytes at a hook site (patch_engine.py P6 writes `jmp stub` there)
 * and jumps back. Keep stack effect and flags identical to the original instructions.
 */
        .intel_syntax noprefix
        .text

#ifndef E32_CLIENT   /* SV_SendClientMessages needsSnapshot: server build only */
/* ---- SV_SendClientMessages (0x4517B0): bool needsSnapshot[18] lived on the stack at
 *      [esp+0x44]; the loop sets it for client indices up to svs.clientCount (32) and
 *      overwrote the adjacent msg_t. Use a 32-byte global instead. ------------------- */

/* hook 0x45181D: `push 0x12 ; lea ecx,[esp+0x48]` (6 bytes) -> memset(G, 0, 32) */
        .globl  _e32_sscm_clear
_e32_sscm_clear:
        push    0x20
        mov     ecx, OFFSET _e32_needSnap
        jmp     0x451823

/* hook 0x451917: `mov byte ptr [esp+ebp+0x44], 1` (5 bytes) — flags from earlier cmp live */
        .globl  _e32_sscm_set
_e32_sscm_set:
        mov     byte ptr [ebp + _e32_needSnap], 1
        jmp     0x45191C

/* hook 0x451963: `cmp byte ptr [esp+edx+0x44], 0` (5 bytes) */
        .globl  _e32_sscm_test
_e32_sscm_test:
        cmp     byte ptr [edx + _e32_needSnap], 0
        jmp     0x451968

#endif

/* ---- r17: session / party tables hold 18 clients ------------------------------------------
 * SessionData.users[18] (0x38 each, at session+0x230) and the lobby's partyMembers[18] (0xE0) are
 * indexed by client slot with no bound. Only REAL players register (bots don't), so a human in
 * slot 18+ overwrote the session's own control fields and, from slot 23, the next session object;
 * dropping them tore down lobby member 31 -> server death (c19). Clients 18+ are kept out of the
 * party/session bookkeeping entirely (IW4x's own GUID/auth, name, rate etc. are unaffected). */

#ifndef E32_CLIENT   /* G1/G2 server party guards: server build only */
/* G1 hook 0x401AAD (SV_UserinfoChanged party/session part): `push 0x6F35F0` (5 bytes). edi = client_t*.
 * Bots already skip this part (je 0x401D69); clients >= 18 take the same exit. The relocated
 * &svs.clients[0] is read from the engine's own `sub ecx, imm32` at 0x401AC2 (operand @0x401AC4),
 * so this works for the patched file and for the in-memory loader alike. eax is free here. */
        .globl  _e32_ui_party
_e32_ui_party:
        mov     eax, dword ptr ds:[0x401AC4]
        add     eax, 18 * 0xA6790
        cmp     edi, eax
        jae     1f
        push    0x6F35F0
        jmp     0x401AB2
1:      jmp     0x401D69

/* G2 hook 0x4C17DC (SV_DropClient's session/lobby removal, esi = clientNum): `push esi; push esi;
 * push 0x66B7008` (7 bytes). Clients >= 18 were never registered -> skip to `pop esi; ret`. */
        .globl  _e32_drop_party
_e32_drop_party:
        cmp     esi, 0x12
        jae     1f
        push    esi
        push    esi
        push    0x66B7008
        jmp     0x4C17E3
1:      jmp     0x4C1849

#endif

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

#ifndef E32_CLIENT   /* C2 SV_DirectConnect check: server build only */
/* C2 hook 0x460561 SV_DirectConnect: `lea edx,[esp+0x54]; push 0x721800` (9 bytes, before the protocol
 * check). userinfo = [esp+0x54], netadr_t from = [esp+0x458] (type first). Unpatched remote client ->
 * same reject path as the original "migration in progress" one (0x460505..0x460560), our message. */
        .globl  _e32_dc_check
_e32_dc_check:
        lea     edx, [esp + 0x54]
        push    dword ptr [esp + 0x458]
        push    edx
        call    _e32_connect_ok
        add     esp, 8
        test    eax, eax
        jz      1f
        lea     edx, [esp + 0x54]
        push    0x721800
        jmp     0x46056A
1:      mov     ecx, dword ptr [esp + 0x458]
        mov     edx, dword ptr [esp + 0x45C]
        push    OFFSET _e32_reject_msg
        sub     esp, 0x14
        mov     eax, esp
        mov     dword ptr [eax], ecx
        mov     ecx, dword ptr [esp + 0x478]
        mov     dword ptr [eax + 4], edx
        mov     edx, dword ptr [esp + 0x47C]
        mov     dword ptr [eax + 8], ecx
        mov     ecx, dword ptr [esp + 0x480]
        mov     dword ptr [eax + 0xC], edx
        push    1
        mov     dword ptr [eax + 0x10], ecx
        call    0x4AEF00
        push    OFFSET _e32_reject_log
        push    0xF
        call    0x413490
        add     esp, 0x24
        pop     edi
        pop     esi
        pop     ebp
        pop     ebx
        add     esp, 0x444
        ret

#endif

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

#ifndef E32_CLIENT
        .data
_e32_reject_msg:
        .asciz  "error\nThis is an IW4x 32-player server. Install the 32-player iw4x.exe + iw4x.dll to join (they also work on normal servers)."
_e32_reject_log:
        .asciz  "    rejected connect: client without the iw4x32 (32-player) build\n"

        .bss
        .balign 64
        .globl  _e32_needSnap
_e32_needSnap:
        .space  64
#endif
