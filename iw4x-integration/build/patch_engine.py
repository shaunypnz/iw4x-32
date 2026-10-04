#!/usr/bin/env python3
"""
patch_engine.py — build a 32-client iw4x.exe from the pristine 18-client engine.

    python3 patch_engine.py [--src PRISTINE] [--dst OUT]

Defaults: --src $MODDED/iw4x.exe.orig32 (MD5 9c42ffa4f7aefd08fd501b40f5e41eab)
          --dst $MODDED/iw4x.exe
Always builds from the pristine exe, so re-running is deterministic (no incremental state).

MW2's engine has MAX_CLIENTS=18 baked in. This script raises it by:

  P1  Adding a zero-filled PE section ".iw432" at VA 0x7100000 that holds enlarged copies
      of every per-client array listed in RELOCS.
  P2  RELOCATING each array: every .text operand (memory displacement or immediate) whose
      value lies inside the old array is shifted to the new copy. This covers exact-base
      refs AND folded field offsets (MSVC folds `arr[i].field` into one displacement, e.g.
      `cmp [eax+0x321AE80],0` = svs_clients+0x41AF0). Per-array EXCLUDE lists keep
      operands that only *look* like they point into the array — loop end-markers of the
      array placed just below it (e.g. g_entities loops whose `cmp esi,END+0x100` lands
      inside level_bgs). SENTINELS handles loop end-markers of the array's own last member
      (`cmp esi,&arr[18].field`), which must move to `&new_arr[32].field`.
  P3  Raising cvar domains (sv_maxclients / ui_maxclients / party_maxplayers) 18 -> 32.
  P4  Byte-size constants that encode "18 elements" (memset sizes, byte-offset loop bounds).
  P5  Code patches (interim clamps, entity layout) — see P5_SITES.
  P6  Code injection: engine32c/ (asm/C, linked at 0x8800000) appended as section .iw4c + jmp hooks.

Every stage checks the exact number of sites it expects and aborts on any mismatch, so a
different input exe fails loudly instead of being half-patched.

STATUS (2026-10-01): server-side arrays svs_clients, level_bgs(+clientinfo[]), g_clients.
NOT YET DONE: entity-number layout (clients 0..17 + 8 body clones = 26 reserved entities),
`cmp reg,0x12` client bounds, level.sortedClients[18], session users[18], and everything
client-side (cg_s, snapshot clients[18], UI). See ENGINE_32_INVENTORY.md.
"""
import argparse, hashlib, os, shutil, struct, sys

import capstone
from capstone.x86 import X86_OP_IMM, X86_OP_MEM

MODDED = "~/Projects/Call of Duty Modern Warfare 2 - modded"
PRISTINE_MD5 = "9c42ffa4f7aefd08fd501b40f5e41eab"
IMAGE_BASE = 0x400000
TEXT_LO, TEXT_HI = 0x1000, 0x2D7000      # .text file offsets (file offset == RVA here)
SECTION_VA = 0x7100000                   # first byte of .iw432 (past image end 0x7033000)
OLD_N, NEW_N = 18, 32

CLIENTINFO_OFF, CLIENTINFO_SZ = 0x82988, 0x52C   # bgs_t::clientinfo[] (last member)
# bgs_t really is 0x886A0 bytes (IW4x Structs.hpp says 0x82950 — wrong); clientinfo[18] at
# +0x82988 (abs: `lea edi,[eax+0x1A40008]`). The 0xF0 bytes after it (0x1A45D20..0x1A45E10)
# are SEPARATE globals (the stock DLL reads [0x1A45DC8]) and must not move.

# name: old region [lo, hi), new region size, expected ref count, excludes, sentinels
RELOCS = [
    dict(name="svs_clients",            # client_s[18], sizeof 0xA6790
         lo=0x31D9390, hi=0x31D9390 + 0xA6790 * OLD_N,
         new_size=0xA6790 * NEW_N,
         expect=115,                    # 82 exact-base + 33 folded-offset
         exclude=set(), sentinels={}),
    dict(name="level_bgs",              # bgs_t: 0x82988 bytes + clientInfo_t clientinfo[18]
         lo=0x19BD680, hi=0x19BD680 + CLIENTINFO_OFF + CLIENTINFO_SZ * OLD_N,   # ..0x1A45D20
         new_size=CLIENTINFO_OFF + CLIENTINFO_SZ * NEW_N,
         expect=35,
         # g_entities (0x18835D8, 2048 x 0x274) loop end-markers that land in bgs:
         exclude={0x4160A3, 0x4754E3},
          # clientinfo[i].field_4FC loops: `cmp esi, 0x1A4621C` (= &clientinfo[18]+0x4FC,
         # which numerically falls inside g_clients)
         sentinels={0x5E48D3: CLIENTINFO_OFF + CLIENTINFO_SZ * NEW_N + 0x4FC,
                    0x5E50C6: CLIENTINFO_OFF + CLIENTINFO_SZ * NEW_N + 0x4FC}),
    dict(name="g_clients",              # gclient_s[18], sizeof 0x366C; level.clients -> here
         lo=0x1A45E10, hi=0x1A45E10 + 0x366C * OLD_N,     # ..0x1A831A8 (= &level)
         new_size=0x366C * NEW_N,
         expect=4,
         exclude={0x5E48D3, 0x5E50C6},  # those are level_bgs clientinfo sentinels (above)
         sentinels={}),
    dict(name="sortedClients",          # level_locals_t::sortedClients[18] @ level+0x3E4
         lo=0x1A8358C, hi=0x1A8358C + 4 * OLD_N,          # ..0x1A835D4 = level.voteString
         new_size=4 * NEW_N,            # CalculateRanks writes one entry per connected client;
         expect=7,                      # with >18 clients it overran into voteString
         exclude=set(), sentinels={}),
    # ---- client side: grow the client's clientinfo[18] -> [32] IN PLACE --------------------
    # cg_s (cgArray 0x7F0F78, 0xFD540) embeds the client's bgs_t at +0x73EB0, whose last member is
    # clientinfo[18] (0x52C each) at 0x8E77B0..0x8ED4C8. Every clientinfo access (absolute, cg-relative
    # and TLS-bgs-relative) stays valid if the array simply extends by 14 entries (+0x4868):
    #  * the globals that follow cg_s (0x8EE4B8..0x8F37D0) move to .iw432 (post_cg_globals);
    #  * cg_s's tail fields (0x8ED4C8..0x8EE4B8, cg+0xFC550..0xFD540) shift up by +0x4868 (14*0x52C) to sit after
    #    the grown array (cg_tail) — both absolute refs and cg-relative displacements;
    #  * the two memset(cg, 0, 0xFD540) grow by the same 0x4868 (P4).
    # The 7 clientinfo loop end-markers inside the tail range (&clientinfo[18].f) shift by +0x4868 too,
    # which is exactly &clientinfo[32].f — so they need no special case.
    dict(name="post_cg_globals",
         lo=0x8EE4B8, hi=0x8F37D0, new_size=0x8F37D0 - 0x8EE4B8,
         expect=216,
         # 0x592B85 `mov [esi*4+0x8F1A8C],eax` has esi in 0x785..0x884 -> real target 0x8F38A0.. (outside)
         # 0x402066 / 0x4E05D6 `mov esi,[ecx*4+0x8EE560]` read the same fx table (0x8F38A0): ecx is a 3-digit
         # ASCII number from a bolted-fx configstring with the '0'*111 bias folded into the disp (r20 fix:
         # relocating them gave a null FxEffectDef -> crash in FX code on entering the AC-130 / thermal)
         exclude={0x592B85, 0x402066, 0x4E05D6}, sentinels={}),
    dict(name="cg_tail",
         lo=0x8ED4C8, hi=0x8EE4B8, new_size=0xFF0,
         fixed_new_lo=0x8ED4C8 + 14 * 0x52C,          # 0x8F1D30 = &clientinfo[32]
         rel_disp=(0xFC550, 0xFD540),                  # cg-relative accesses to the tail
         expect=256, expect_rel=21, exclude=set(), sentinels={}),
    # UI player list (sharedUiInfo @0x62E4B78): UI_BuildPlayerList (0x631870) loops to the server's
    # sv_maxclients and appends every connected player -> playerNames[18][32] / playerClientNums[18]
    # overflowed into teamNames (unused in MP) and the game-type list. Move both to 32 entries.
    dict(name="ui_playerNames", lo=0x62E4BD4, hi=0x62E4BD4 + 0x20 * OLD_N, new_size=0x20 * NEW_N,
         expect=3, exclude=set(), sentinels={}),
    dict(name="ui_playerClientNums", lo=0x62E5054, hi=0x62E5054 + 4 * OLD_N, new_size=4 * NEW_N,
         expect=4, exclude=set(), sentinels={}),   # (memset(-1, 0x48) at init covers 18; entries are set before use)
    # Scoreboard rows (cg scores) @0x863C38, 18 x 0x28; count @0x863C04 clamped to 18 by the scores
    # parser (0x591F20) -> scoreboard listed at most 18 players. Rows move to 32 entries; two
    # 1-based accesses use the folded base &rows[-1] = 0x863C10 (which is ALSO a scalar header field —
    # only the two [reg*8+0x863C10] sites are row accesses).
    dict(name="cg_scores", lo=0x863C38, hi=0x863C38 + 0x28 * OLD_N, new_size=0x28 * NEW_N,
         expect=9, exclude=set(),
         sentinels={0x416494: -0x28, 0x41649B: -0x28}),
    # ---- r22: client compass/minimap actor table [26] x 0x3C (players 0..17 = clientNum, 8 corpse actors at
    # 18..25 via the slot map, fn 0x57F6C0) -> [40] (players 0..31, corpses 32..39). 0x7D85C0 is the NEXT object
    # (memset separately in fn 0x4B2140), so the table is exactly [0x7D7FA8, 0x7D85C0). Folded corpse base
    # 0x7D83E0 (= entry 18) -> entry 32. Code constants (bounds, loop counts, strides): P5 D8. Sites mapped by
    # qwen27b (Q12, docs-audit/q12/), verified against the disassembly.
    dict(name="compass_actors", lo=0x7D7FA8, hi=0x7D85C0, new_size=40 * 0x3C,
         expect=11, exclude=set(), sentinels={0x57F707: 32 * 0x3C}),
    dict(name="cl_ring44",              # per-client 8-deep ring {int a[8]; int b[8]; int idx}
         lo=0x62C8228, hi=0x62C8228 + 0x44 * OLD_N,       # ..0x62C86F0; writer fn 0x4C3D30
         new_size=0x44 * NEW_N,         # caught by hw watchpoint: client 18 overwrote the
         expect=3,                      # loc_language dvar ptr @0x62C8704 with 5
         exclude=set(), sentinels={}),
    # ---- r15: client voice receive state (Voice_Init 0x4A2230, Voice_IncomingVoiceData 0x5001A0,
    # Voice_IsClientTalking 0x4D9D20). IW4x's CL_VoicePacket accepts talker < 32 and its
    # CL_IsPlayerTalking hook asks Voice_IsClientTalking(clientNum) for every scoreboard row, so with
    # 32 rows talkTime[18] was read out of bounds -> phantom "talking" icons for players 19..32, and
    # with sv_voice 1 a talker >= 18 used talkTime[] as a decoder handle (crash).
    dict(name="cl_voiceDecoders",       # int decoders[18]; loops end at &decoders[18] (= talkTime)
         lo=0x64A39E0, hi=0x64A39E0 + 4 * OLD_N, new_size=4 * NEW_N, expect=5, exclude=set(),
         sentinels={0x445032: 4 * NEW_N, 0x4A23EB: 4 * NEW_N, 0x4B4C08: 4 * NEW_N}),
    dict(name="cl_voiceTalkTime",       # int talkTime[18] (memset 0x48 at 0x4A23C1 left as is:
         lo=0x64A3A28, hi=0x64A3A28 + 4 * OLD_N, new_size=4 * NEW_N, expect=3,   # .iw432 starts zeroed)
         exclude={0x445032, 0x4A23EB, 0x4B4C08}, sentinels={}),
    dict(name="snd_voiceBufPool",       # bump-allocator pool, 19 x 0x48 (18 decoders + 1): 32
         lo=0x1AA5E48, hi=0x1AA63A0, new_size=33 * 0x48,  # decoders would overrun into the
         expect=1, exclude=set(), sentinels={}),          # IDirectSound* at 0x1AA63A4
]

# P3: cvar domain clamps. (file_offset, label): `push 0x12` -> `push 0x20`.
# Dvar_Create @0x479830 (name, value, min, max, flags, help). At sites #2/#3 sv_maxclients'
# max is ui_maxclients' current value, so both ui immediates must be raised there.
P3_SITES = (
    (0x26188,  "site#1 ui_maxclients value"),
    (0x2618C,  "site#1 ui_maxclients max"),
    (0x261A8,  "site#1 sv_maxclients value"),
    (0xD374F,  "site#2 ui_maxclients max (dedicated path)"),
    (0xD3753,  "site#2 ui_maxclients value"),
    (0x1E376B, "site#3 ui_maxclients max"),
    (0x1E376F, "site#3 ui_maxclients value"),
    (0xD5D5D,  "party_maxplayers max"),
)

# P4: imm32 byte-size constants: (instruction VA, old value, new value, label)
P4_SITES = (
    (0x48EEE9, 0x366C * OLD_N, 0x366C * NEW_N, "G_InitGame memset(g_clients) size"),
    (0x5F9921, 0x366C * OLD_N, 0x366C * NEW_N, "loop over level.clients[] byte bound"),
    (0x4AD333, 0xFD540, 0xFD540 + 14 * 0x52C, "CG_Init memset(cg) size incl. grown clientinfo"),
    (0x4E32B4, 0xFD540, 0xFD540 + 14 * 0x52C, "memset(cg) size incl. grown clientinfo"),
    (0x40C1E6, 0x28 * OLD_N, 0x28 * NEW_N, "memset(cg_scores rows) size"),
    (0x59200F, 0x28 * OLD_N, 0x28 * NEW_N, "CG_ParseScores memset(cg_scores rows) size"),
)


# P5: code patches — (VA, expected old bytes, new bytes, label). INTERIM clamps for code that
# keeps per-client data in stack frames / caller-owned structs sized [18] (cannot be fixed by
# relocating globals; needs a proper re-implementation in the DLL later).
P5_SITES = (
    # (Anti-lag clamps removed in r8 — G_AntiLagRewind/Restore are replaced by engine32c/antilag.c
    #  via P6 hooks, which handle all 32 slots with a global AntilagStore32.)

    # D: entity layout. Pristine: clients = entities 0..17, body clones 18..25, first free 26.
    # New: clients 0..31, SPARE 32..35 (never spawned, stay zeroed), clones 36..43, first free 44.
    # The spare block lets 0x416250's x6-unrolled player loop run to entity 36 without a code cave.
    (0x48EF4C, "6a1a", "6a2c", "G_InitGame: SV_LocateGameData num_entities 26 -> 44"),
    (0x48EF53, "c705b031a8011a000000", "c705b031a8012c000000", "G_InitGame: level.num_entities = 26 -> 44"),
    (0x4FC5C6, "8d7012", "8d7024", "body clone entnum = 18 + currentPlayerClone -> 36 + .."),
    (0x44CB07, "83f81a", "83f82c", "G_FreeEntity: entnum < 26 (reserved, never freed) -> 44"),
    (0x41635C, "3d58638801", "3d808f8801", "0x416250 loop1 (unrolled x6) end &g_entities[18].client -> [36]"),
    (0x4163A4, "81fe58638801", "81fe808f8801", "0x416250 loop2 end &g_entities[18].client -> [36]"),
    (0x4C50C2, "83fb12", "83fb20", "entnum < MAX_CLIENTS check 18 -> 32"),
    (0x58E175, "83fb12", "83fb20", "entnum < MAX_CLIENTS check 18 -> 32"),
    (0x59DF11, "837c244412", "837c244420", "entnum < MAX_CLIENTS check 18 -> 32"),
    (0x628560, "833812", "833820", "SV entity archive: skip player entities (entnum < MAX_CLIENTS) 18 -> 32"),
    # D2: client side of the entity layout. cg keeps clientInfo_t corpseinfo[8] @0x7EE5F4 (0x52C each)
    # indexed by (entnum - 18), and cg_entities[18 + corpseIndex] for the local player's own body.
    # With body clones at 36..43 these must use 36, otherwise cg indexes corpseinfo[18..25] — out of
    # bounds into cg_s snapshot memory — and dies on a null pXAnimTree (c10: crash at 0x468D78 while
    # drawing corpse entity 36). corpseinfo[k] = 0x7EE5F4 + k*0x52C; folded bases shift by 18*0x52C.
    (0x4D76F4, "83e812", "83e824", "corpse: corpseinfo[entnum - 18] -> [entnum - 36] (sub eax)"),
    (0x4E8564, "8d70ee", "8d70dc", "CG_PlayerCorpse: corpseinfo[entnum - 18] -> [entnum - 36] (lea esi)"),
    (0x595295, "83ee12", "83ee24", "corpse: corpseinfo[entnum - 18] -> [entnum - 36] (sub esi)"),
    (0x5955AE, "8bb8d88d7e00", "8bb8c0307e00", "corpse: folded corpseinfo[entnum-18].pXAnimTree 0x7E8DD8 -> 0x7E30C0"),
    (0x5955B4, "8bb0848c7e00", "8bb06c2f7e00", "corpse: folded corpseinfo[entnum-18]+0x3A8 0x7E8C84 -> 0x7E2F6C"),
    (0x5955BA, "8d80dc887e00", "8d80c42b7e00", "corpse: folded &corpseinfo[entnum-18] 0x7E88DC -> 0x7E2BC4"),
    (0x4664DF, "81c6f0608f00", "81c638858f00", "cg: own body cg_entities[18 + idx] -> [36 + idx] (0x8F60F0 -> 0x8F8538)"),
    (0x595F88, "81c6f0608f00", "81c638858f00", "cg: own body cg_entities[18 + idx] -> [36 + idx] (0x8F60F0 -> 0x8F8538)"),
    # D3 (r15): plain `entnum < MAX_CLIENTS` ("is a player") checks found by the r14 adversarial
    # review + loop triage. Corpses (36..43) stay on the non-player side exactly as in stock.
    (0x4D767F, "83bedc00000012", "83bedc00000020", "cg lerp: trType 3 player interpolation entnum < 18 -> 32"),
    (0x45D5C1, "83fe12", "83fe20", "cg entity eye position: add view height for entnum < 18 -> 32"),
    (0x581E33, "6683fb12", "6683fb20", "cg crosshair trace: hit is a player (names) < 18 -> 32"),
    (0x4B1B0C, "663d1200", "663d2000", "pmove trace: hit is a player < 18 -> 32"),
    (0x5E6136, "663d1200", "663d2000", "missile trace: hit is a player < 18 -> 32"),
    (0x5E5422, "663d1200", "663d2000", "missile trace: hit is a player < 18 -> 32"),
    (0x5E5B24, "663d1200", "663d2000", "missile trace: hit is a player < 18 -> 32"),
    (0x5F6E50, "833812", "833820", "GScr showToPlayer: player entnum < 18 -> 32"),
    (0x425238, "be12000000", "be20000000", "G_GetNonPVSPlayerInfo (compass teammates): modulo 18 -> 32"),
    (0x425295, "83ff12", "83ff20", "G_GetNonPVSPlayerInfo: loop count 18 -> 32"),
    # entityState.clientMask builder (fn 0x5E2990, edx = gentity): the x6-unrolled loop covered 18
    # clients and no bound covers exactly 32 (30 + 6 would OR bits into r.isLinked at +0x100), so the
    # head is rewritten as a plain 32-iteration loop; the old body after 0x5E29BE becomes dead code.
    (0x5E2990, "53555657c782fc00000000000000b802000000bf943a0000bb000040008d49008b0da831a801859c0f94c9ffff75",
     "568b35a831a80133c033c9f786280400000000400075030fabc881c66c3600004183f92072e58982fc0000005ec3",
     "clientMask builder: compact loop over 32 clients (bit i set unless gclient+0x428 & 0x400000)"),
    # Host migration state only has room for 18 clients (0x62C7C54 x0x18, 0x62C7E04, state struct);
    # IW4x disables migration but `hostmigration_start` still reaches SV_MigrationStart -> always take
    # its own "migration limit reached, ending match" path.
    (0x4D180E, "7c21", "9090", "SV_MigrationStart: never migrate (end match instead)"),
    # D4 (r16): 'clientNum < 18' validity checks that end in an error (sweep of every 17/18/19
    # compare near an error/print call). CG_Obituary's was found live: the first death of a player
    # in slot 19+ disconnected every patched client with "CG_Obituary: target out of range".
    (0x586D99, "83ff12", "83ff20", "CG_Obituary: target clientNum < 18 -> 32 (else Com_Error drop)"),
    (0x5D847C, "83f812", "83f820", "ClientScr sessionteam setter: client index < 18 -> 32 (else Scr_Error)"),
    (0x5D8742, "83fe12", "83fe20", "ClientScr forceSpectatorClient setter: < 18 -> 32 (else Scr_Error)"),
    (0x4B9B0C, "83ff12", "83ff20", "WriteField1 (archive): gclient index < 18 -> 32"),
    (0x4EFC40, "83ff12", "83ff20", "ReadField (archive): gclient index < 18 -> 32"),
    # D6 (r19): the cg_tail shift (r10) moved cg-relative DISPLACEMENTS in [0xFC550,0xFD540) but this
    # cg-relative offset is an IMMEDIATE: `lea esi,[edi+0xFCD48] (shifted); add edi,0xFC8E8; mov ecx,0x1C;
    # rep movsd` copied 0x70 bytes onto the OLD tail address = clientinfo[18].legs (client crash at the
    # end-of-match intermission, c28; writer caught with a hardware watchpoint, c29). Only such immediate.
    (0x59AEFC, "81c7e8c80f00", "81c750111000", "cg: tail copy destination cg+0xFC8E8 -> +0x4868 (0x101150)"),
    # D8 (r22): compass actor table 26 -> 40 entries (RELOCS compass_actors). Per-local-client strides are
    # multiplied by localClientNum (always 0 in MP) but are changed too, for consistency.
    (0x442249, "83ff12", "83ff20", "compass: actor index < 18 = player (else corpse) -> 32"),
    (0x4422D5, "83ff12", "83ff20", "compass: player actor: copy client position (< 18 -> 32)"),
    (0x44232B, "83ff12", "83ff20", "compass: player actor: name / cg lookup (< 18 -> 32)"),
    (0x4422A8, "6bc91a", "6bc928", "compass: per-local-client stride 26 -> 40 actors"),
    (0x4423A0, "6bf61a", "6bf628", "compass: per-local-client stride 26 -> 40 actors"),
    (0x57FEB6, "6bc91a", "6bc928", "compass: per-local-client stride 26 -> 40 actors"),
    (0x46CD81, "69f618060000", "69f660090000", "compass: per-local-client table size 0x618 -> 0x960"),
    (0x4FE146, "69ff18060000", "69ff60090000", "compass: per-local-client table size 0x618 -> 0x960"),
    (0x57F6FF, "69c018060000", "69c060090000", "compass: per-local-client table size 0x618 -> 0x960"),
    (0x58A0EF, "69ff18060000", "69ff60090000", "compass: per-local-client table size 0x618 -> 0x960"),
    (0x58A1D3, "69f618060000", "69f660090000", "compass: per-local-client table size 0x618 -> 0x960"),
    (0x58AB87, "69ff18060000", "69ff60090000", "compass: per-local-client table size 0x618 -> 0x960"),
    (0x4B2140, "6818060000", "6860090000", "compass: memset(actor table) size 0x618 -> 0x960"),
    (0x46CD97, "c744242812000000", "c744242820000000", "compass: player actor loop count 18 -> 32"),
    (0x58A0FE, "bb1a000000", "bb28000000", "compass: all-actor loop count 26 -> 40"),
    (0x58A1E8, "bb1a000000", "bb28000000", "compass: all-actor loop count 26 -> 40"),
    (0x58AB9E, "c74424101a000000", "c744241028000000", "compass: all-actor loop count 26 -> 40"),
    (0x57F73F, "8d4112", "8d4120", "compass: corpse actor index = slot + 18 -> + 32"),
    (0x57FD61, "69f618060000", "69f660090000", "compass: per-local-client table size 0x618 -> 0x960"),
    (0x58B03E, "69f618060000", "69f660090000", "compass: per-local-client table size 0x618 -> 0x960"),
    (0x58B062, "c74424141a000000", "c744241428000000", "compass: all-actor loop count 26 -> 40"),
    # D7 (r21): renderer skinned-vertex cache, R_MAX_SKINNED_CACHE_VERTICES (1024*144 verts * 32 B = 0x480000
    # bytes) is too small for 32 players + bodies in view ("exceeded - not drawing surface" -> invisible
    # players, c39). Two D3DPOOL_DEFAULT vertex buffers (one per frame parity, created in fn 0x51E810) are
    # locked whole (size 0, DISCARD, fn 0x50FA20), so growing size + capacity + check together is enough:
    # 0x480000 -> 0x900000 (2 x 9 MB VRAM). Found by qwen27b (Q10, docs-audit/q10_skinned_cache.md). The
    # TEMP_SKIN_BUF check (0x549F54) shares the constant but guards a different buffer: unchanged.
    (0x51E8B9, "c747fc00004800", "c747fc00009000", "skinned cache: descriptor capacity 0x480000 -> 0x900000"),
    (0x51E8D8, "6800004800", "6800009000", "skinned cache: CreateVertexBuffer length 0x480000 -> 0x900000"),
    (0x51E8EB, "6800004800", "6800009000", "skinned cache: size in the create-failure message"),
    (0x549E43, "81f900004800", "81f900009000", "skinned cache: per-surface capacity check 0x480000 -> 0x900000"),
    # D5 (r18): remaining clientNum/entnum < 18 bounds from qwen27b's ENTNUM triage (Q7b), each
    # verified against the disassembly: all index arrays that are 32 entries now.
    (0x5713FE, "83f912", "83f920", "BG TLS clientinfo accessor: NULL for clientNum >= 18 -> 32 (server+client)"),
    (0x4D49B9, "83fd12", "83fd20", "cg entity: player-only path for entnum < 18 -> 32"),
    (0x4DD034, "83f812", "83f820", "cg event: clientNum clamp before clientinfo[] 18 -> 32"),
    (0x582374, "83fd12", "83fd1f", "cg crosshair owner: clientinfo[n] for n <= 18 (jg) -> n <= 31"),
    (0x588041, "83f812", "83f820", "cg event: clientinfo[clientNum] bound 18 -> 32"),
    (0x5D7C17, "83f812", "83f820", "spectate/follow target clientNum validated < 18 -> 32"),
    (0x5DF2CA, "83fe12", "83fe20", "GSC builtin: clientnum arg < 18 -> 32 (else script error)"),
    (0x5F624A, "83f812", "83f820", "GSC builtin: clientnum <= 18 -> 32 (else param error)"),
    # E: client side
    (0x46553A, "83fe12", "83fe20", "talker HUD list: scan clientNums 0..31 (talkTime[] relocated in r15)"),
    (0x5AC62E, "83f812", "83f820", "CL_ParseGamestate: clientNum >= MAX_CLIENTS -> 'bad clientNum' 18 -> 32"),
    (0x586E05, "83fb11", "83fb1f", "cg: client index <= 17 check before clientinfo[] -> <= 31"),
    (0x591F5F, "83f812", "83f820", "CG_ParseScores: numScores clamp 18 -> 32 (compare)"),
    (0x591F69, "c705043c860012000000", "c705043c860020000000", "CG_ParseScores: numScores clamp 18 -> 32 (store)"),
    # snapshot_s = {.., entityState_s entities[768] @+0x3130 (0x100 each), clientState_s clients[18]
    # @+0x33130 (0x7C each), int serverCommandSequence @+0x339E8}. CL_GetSnapshot (0x46B7C0) silently
    # copied only 18 clientStates, so the client never learned about players 19..32 (verified live:
    # cg clientinfo[18..31] stayed empty). Make room for clients[32] WITHOUT moving anything else:
    # cap snapshot entities at 761 (0x2F9) and start clients 14 entries earlier (+0x32A68 = 0x33130 -
    # 14*0x7C); clients[32] then ends exactly at +0x339E8 as before. Only 7 instructions in 3
    # functions address snapshot clients (no absolute refs) — all rewritten here.
    (0x46B888, "81ff00030000", "81fff9020000", "CL_GetSnapshot: entity cap 768 -> 761 (compare)"),
    (0x46B8DC, "c744241c00030000", "c744241cf9020000", "CL_GetSnapshot: entity cap 768 -> 761 (clamp)"),
    (0x46B8B0, "6800030000", "68f9020000", "CL_GetSnapshot: truncation warning arg 768 -> 761"),
    (0x46B8C7, "6800030000", "68f9020000", "CL_GetSnapshot: truncation warning arg 768 -> 761"),
    (0x46B980, "83f812", "83f820", "CL_GetSnapshot: clientState cap 18 -> 32 (compare)"),
    (0x46B989, "c744241c12000000", "c744241c20000000", "CL_GetSnapshot: clientState cap 18 -> 32 (clamp)"),
    (0x46B9A1, "81c630310300", "81c6682a0300", "CL_GetSnapshot: snap->clients base +0x33130 -> +0x32A68"),
    (0x4502EE, "81c534310300", "81c56c2a0300", "cg snapshot processing: &snap->clients[0].f +0x33134 -> +0x32A6C"),
    (0x45099C, "81c730310300", "81c7682a0300", "cg snapshot processing: snap->clients base -> +0x32A68"),
    (0x594F20, "8bb42830310300", "8bb428682a0300", "cg: snap->clients[i] read -> +0x32A68"),
    (0x594F27, "8d9c2830310300", "8d9c28682a0300", "cg: &snap->clients[i] -> +0x32A68"),
)


# P6: code injection. engine32c/ is built (engine32c/build.sh) into a raw image linked at
# E32C_BASE and appended as an executable section `.iw4c`; hook sites get `jmp <stub>`.
E32C_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine32c")
E32C_BASE = 0x8800000
P6_HOOKS = (
    # SV_SendClientMessages (0x4517B0): bool needsSnapshot[18] on the stack, set for client
    # indices < svs.clientCount (32) -> overwrote the adjacent msg_t. Use a 32-byte global.
    (0x45181D, "6a128d4c2448", "_e32_sscm_clear", "SV_SendClientMessages: memset(needsSnapshot,0,18) -> global[32]"),
    (0x451917, "c6442c4401", "_e32_sscm_set", "SV_SendClientMessages: needsSnapshot[i] = 1 -> global"),
    (0x451963, "807c144400", "_e32_sscm_test", "SV_SendClientMessages: needsSnapshot[i] test -> global"),
    # Lag compensation for 32 clients (engine32c/antilag.c): replace the two entry points.
    # Rewind's caller-owned AntilagClientStore (sized 18) is ignored in favour of a global store.
    (0x4C1120, "81ecc8010000", "_e32_AntiLagRewind", "G_AntiLagRewindClientPos -> 32-client C version"),
    (0x440040, "833d4c35a80100", "_e32_AntiLagRestore", "G_AntiLagRestoreClientPos -> 32-client C version"),
    # r17: keep clients >= 18 out of the 18-entry session users[] / lobby partyMembers[] (stubs.S G1-G5).
    (0x401AAD, "68f0356f00", "_e32_ui_party", "SV_UserinfoChanged: party/session part only for clients < 18 (like bots)"),
    (0x4C17DC, "56566808706b06", "_e32_drop_party", "SV_DropClient session/lobby removal: only clientNum < 18"),
    (0x487C10, "8b4424088b542404", "_e32_xuid_for_slot", "Session_GetXuidForSlot: slot >= 18 -> 0"),
    (0x49ABB0, "83ec14568b74241c", "_e32_set_addr", "Session_SetClientAddress: slot >= 18 -> return"),
    (0x4D3D00, "83ec285355", "_e32_member_teardown", "PartyHost member teardown: slot >= 18 -> return"),
    # r22 compat: marker dvar, unpatched clients refused by a 32-player server, client layout switch (engine32c/compat.c)
    (0x4261B5, "a3908d0902", "_e32_marker_hook", "SV_SpawnServer: register dvar iw4x32, force the 32-player layout"),
    (0x4D9571, "6830427200", "_e32_cl_init_hook", "CL_Init: register dvar iw4x32 (sent in userinfo)"),
    (0x460561, "8d5424546800187200", "_e32_dc_check", "SV_DirectConnect: refuse remote clients without iw4x32\\1"),
    (0x4CCF44, "68b0b56f00", "_e32_cg_si_hook", "CG_ParseServerinfo: stock vs 32-player body layout switch"),
)


def die(msg):
    sys.exit(f"ERROR: {msg}")


# ---- change recorder (--manifest): every byte range the build writes, with the reason -----------------------------
WRITES = []      # (file offset, length, label)
CUR = ""         # label for operand rewrites of the current stage


def note(fo, n, label):
    WRITES.append((fo, n, label))


def text_operands(d):
    """Yield (va, insn, value, kind) for every mem-disp / imm operand in .text."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    off = TEXT_LO
    while off < TEXT_HI:
        progressed = False
        for ins in md.disasm(bytes(d[off:min(off + 0x4000, TEXT_HI)]), IMAGE_BASE + off):
            progressed = True
            off = ins.address - IMAGE_BASE + ins.size
            for op in ins.operands:
                if op.type == X86_OP_MEM:
                    yield ins.address, ins, op.mem.disp & 0xFFFFFFFF, ("memrel" if (op.mem.base or op.mem.index) else "mem")
                elif op.type == X86_OP_IMM:
                    yield ins.address, ins, op.imm & 0xFFFFFFFF, "imm"
            if off >= TEXT_HI:
                break
        if not progressed:
            off += 1


def rewrite_operand(d, ins, old, new):
    raw = bytes(ins.bytes)
    le = struct.pack("<I", old)
    k = raw.find(le)
    if k < 0 or raw.find(le, k + 1) >= 0:
        die(f"cannot uniquely locate {old:#x} in {ins.address:#x} {ins.mnemonic} {ins.op_str}")
    fo = ins.address - IMAGE_BASE + k
    d[fo:fo + 4] = struct.pack("<I", new)
    note(fo, 4, CUR or f"operand {old:#x} -> {new:#x}")


def layout():
    va = SECTION_VA
    for r in RELOCS:
        if "fixed_new_lo" in r:
            r["new_lo"] = r["fixed_new_lo"]
            continue
        r["new_lo"] = va
        va = (va + r["new_size"] + 0xFFF) & ~0xFFF
    return va - SECTION_VA


def p1_section(d, vsize):
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    if d[pe:pe + 4] != b"PE\0\0":
        die("not a PE file")
    coff = pe + 4
    nsec = struct.unpack_from("<H", d, coff + 2)[0]
    opt_size = struct.unpack_from("<H", d, coff + 16)[0]
    opt = coff + 20
    if struct.unpack_from("<I", d, opt + 0x1C)[0] != IMAGE_BASE:
        die("unexpected ImageBase")
    if nsec != 6:
        die(f"expected 6 sections in pristine exe, found {nsec}")
    sect = opt + opt_size
    ins = sect + 6 * 40
    if any(d[ins:ins + 40]):
        die("no free slot for a 7th section header")
    rva = SECTION_VA - IMAGE_BASE
    hdr = b".iw432\0\0" + struct.pack("<IIIIIIHHI", vsize, rva, 0, 0, 0, 0, 0, 0, 0xC0000080)
    d[ins:ins + 40] = hdr                         # rw, uninitialized data (zero-filled)
    struct.pack_into("<H", d, coff + 2, 7)
    size_of_image = (rva + vsize + 0xFFF) & ~0xFFF
    struct.pack_into("<I", d, opt + 0x38, size_of_image)
    note(ins, 40, "PE header: new section .iw432 (zero-filled data: enlarged per-player arrays, no file bytes)")
    note(coff + 2, 2, "PE header: NumberOfSections")
    note(opt + 0x38, 4, "PE header: SizeOfImage")
    print(f"P1  .iw432 @ {SECTION_VA:#x} size {vsize:#x}, SizeOfImage -> {size_of_image:#x}")
    for r in RELOCS:
        print(f"      {r['name']:12s} {r['lo']:#x}..{r['hi']:#x} -> {r['new_lo']:#x} "
              f"(+{r['new_size']:#x})")


def p2_relocate(d):
    ops = list(text_operands(d))
    global CUR
    for r in RELOCS:
        lo, hi, delta = r["lo"], r["hi"], r["new_lo"] - r["lo"]
        CUR = (f"relocate array {r['name']} {r['lo']:#x}..{r['hi']:#x} -> {r['new_lo']:#x} "
               f"(+{r['new_size']:#x}, room for 32 players): address operand")
        n = nrel = 0
        rlo, rhi = r.get("rel_disp", (1, 0))
        for va, ins, v, kind in ops:
            if va in r["exclude"] or va in r["sentinels"]:
                continue
            if lo <= v < hi:
                rewrite_operand(d, ins, v, v + delta)
                n += 1
            elif kind == "memrel" and rlo <= v < rhi:
                rewrite_operand(d, ins, v, (v + delta) & 0xFFFFFFFF)
                nrel += 1
        for va, new_off in r["sentinels"].items():
            hit = [(i, v) for a, i, v, k in ops if a == va]
            if len(hit) != 1:
                die(f"{r['name']}: sentinel site {va:#x} has {len(hit)} operands")
            ins, v = hit[0]
            rewrite_operand(d, ins, v, r["new_lo"] + new_off)
            print(f"      sentinel {va:#x}: {v:#x} -> {r['new_lo'] + new_off:#x}")
        if r["expect"] is not None and n != r["expect"]:
            die(f"{r['name']}: expected {r['expect']} refs, rewrote {n}")
        if "rel_disp" in r and r.get("expect_rel") is not None and nrel != r["expect_rel"]:
            die(f"{r['name']}: expected {r['expect_rel']} reg-relative disps, rewrote {nrel}")
        CUR = ""
        print(f"P2  {r['name']}: {n} refs relocated (+{len(r['sentinels'])} sentinels, "
              f"{len(r['exclude'])} excluded" + (f", {nrel} reg-relative disps" if "rel_disp" in r else "") + ")")


def p3_cvars(d):
    for off, what in P3_SITES:
        if d[off] != 0x6A or d[off + 1] != 0x12:
            die(f"P3 {what} @{off:#x}: expected 6A 12, found {d[off]:02X} {d[off+1]:02X}")
        d[off + 1] = 0x20
        note(off + 1, 1, f"cvar domain 18 -> 32: {what}")
    print(f"P3  {len(P3_SITES)} cvar domain sites 18 -> 32")


def p4_sizes(d):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    for va, old, new, what in P4_SITES:
        fo = va - IMAGE_BASE
        ins = next(md.disasm(bytes(d[fo:fo + 16]), va, count=1))
        global CUR
        CUR = f"{va:#x} size constant {old:#x} -> {new:#x}: {what}"
        rewrite_operand(d, ins, old, new)
        CUR = ""
        print(f"P4  {va:#x} {what}: {old:#x} -> {new:#x}")


def p5_code(d):
    for va, old, new, what in P5_SITES:
        fo = va - IMAGE_BASE
        ob, nb = bytes.fromhex(old), bytes.fromhex(new)
        if len(ob) != len(nb):
            die(f"P5 {va:#x}: length mismatch")
        if bytes(d[fo:fo + len(ob)]) != ob:
            die(f"P5 {va:#x} {what}: expected {old}, found {bytes(d[fo:fo + len(ob)]).hex()}")
        d[fo:fo + len(nb)] = nb
        note(fo, len(nb), f"{va:#x} code: {what}")
        print(f"P5  {va:#x} {what}")


# Compat (r22): code sites whose 32-player bytes are WRONG on a stock 18-player server (players vs dead bodies by
# entity number, corpse index base). The client writes them back to the pristine bytes when the server does not
# advertise iw4x32 (engine32c/compat.c, e32_set_layout), and restores ours when it does. Filled from qwen27b's Q14
# classification after manual verification (docs-audit/q14_review.md).
DUAL_SITES = tuple((va, 0) for va in (      # (VA, length) — length taken from P5_SITES below
    # body clones: layout (entities 36..43 vs stock 18..25) — client corpse code + server allocation
    0x4D76F4, 0x4E8564, 0x595295, 0x5955AE, 0x5955B4, 0x5955BA, 0x4664DF, 0x595F88, 0x4FC5C6, 0x44CB07,
    # "entity number < N means a player" (stock servers have ordinary entities at 26..31 too)
    0x4D767F, 0x45D5C1, 0x581E33, 0x4D49B9, 0x4B1B0C, 0x4C50C2, 0x58E175, 0x59DF11,
    0x5E6136, 0x5E5422, 0x5E5B24, 0x5F6E50, 0x628560,
    # server entity layout (only reverted when the process hosts a <= 18-slot server: compatibility mode)
    0x48EF4C, 0x48EF53, 0x41635C, 0x4163A4,
))
PRISTINE = None

# ---- build roles -------------------------------------------------------------------------------------------------
# "server" (default): everything above — our 32-player dedicated servers. Output unchanged (r23 = 7c524518...).
# "client": the PUBLIC player build. Only what a player needs to play on a 32-player server; every server-side
# change is left out, so the public exe hosts at most 18 players (stock server layout, stock cvar domains) and
# cannot be turned into a 32-player server without redoing the server work. Sites classified by the globals their
# functions touch (tools-re/site_data_role.py: g_entities / level / g_clients / svs.clients = server) + the RE labels.
ROLE = "server"
SERVER_ONLY_RELOCS = {"svs_clients", "level_bgs", "g_clients", "sortedClients"}
SERVER_ONLY_VAS = {
    # P4: G_InitGame memset(g_clients), level.clients loop bound
    0x48EEE9, 0x5F9921,
    # P5: server entity layout (num_entities, body clones, G_FreeEntity, g_entities loops) + SV entity archive
    0x48EF4C, 0x48EF53, 0x4FC5C6, 0x44CB07, 0x41635C, 0x4163A4, 0x628560,
    # P5: G_ missile traces, GScr showToPlayer, G_GetNonPVSPlayerInfo, clientMask builder, SV_MigrationStart,
    #     ClientScr setters, archive fields, GSC builtins
    0x5E6136, 0x5E5422, 0x5E5B24, 0x5F6E50, 0x425238, 0x425295, 0x5E2990, 0x4D180E,
    0x5D847C, 0x5D8742, 0x4B9B0C, 0x4EFC40, 0x5DF2CA, 0x5F624A,
    # P6: SV_SendClientMessages needsSnapshot, anti-lag, SV party guards, SV_DirectConnect check
    0x45181D, 0x451917, 0x451963, 0x4C1120, 0x440040, 0x401AAD, 0x4C17DC, 0x460561,
}


def apply_role(role):
    """Filter the site tables for a build role (call before layout())."""
    global ROLE, RELOCS, P3_SITES, P4_SITES, P5_SITES, P6_HOOKS, DUAL_SITES
    if role not in ("server", "client"):
        die(f"unknown role {role}")
    ROLE = role
    if role == "server":
        return
    RELOCS = [r for r in RELOCS if r["name"] not in SERVER_ONLY_RELOCS]
    P3_SITES = ()                                   # stock cvar domains: sv_maxclients <= 18
    P4_SITES = tuple(x for x in P4_SITES if x[0] not in SERVER_ONLY_VAS)
    P5_SITES = tuple(x for x in P5_SITES if x[0] not in SERVER_ONLY_VAS)
    P6_HOOKS = tuple(x for x in P6_HOOKS if x[0] not in SERVER_ONLY_VAS)
    DUAL_SITES = tuple(x for x in DUAL_SITES if x[0] not in SERVER_ONLY_VAS)


def fill_dual_table(blob, syms):
    if "_e32_dual_tab" not in syms:
        return blob
    blob = bytearray(blob)
    tab = syms["_e32_dual_tab"] - E32C_BASE
    if struct.unpack_from("<I", blob, tab)[0] != 0xE32D0A1:
        die("P6: _e32_dual_tab placeholder not found in the blob")
    if len(DUAL_SITES) >= 96:
        die("P6: too many DUAL_SITES (max 95)")
    p5 = {va: (old, new) for va, old, new, what in P5_SITES}
    for i, (va, n) in enumerate(DUAL_SITES):
        if va not in p5:
            die(f"P6 dual {va:#x}: not a P5 site")
        old = bytes.fromhex(p5[va][0])
        n = n or len(old)
        if not 0 < n <= 12:
            die(f"P6 dual {va:#x}: bad length {n}")
        stock = PRISTINE[va - IMAGE_BASE: va - IMAGE_BASE + n]
        if stock != old[:n]:      # P2 relocated an operand here: the pristine bytes would point at a moved array
            die(f"P6 dual {va:#x}: pristine {stock.hex()} != P5 old {old.hex()} (relocated operand?)")
        struct.pack_into("<II", blob, tab + 20 * i, va, n)
        blob[tab + 20 * i + 8: tab + 20 * i + 8 + n] = stock
    struct.pack_into("<II", blob, tab + 20 * len(DUAL_SITES), 0, 0)
    print(f"P6  compat: {len(DUAL_SITES)} layout-dependent sites in _e32_dual_tab")
    return bytes(blob)


def p6_inject(d):
    import subprocess
    r = subprocess.run(["bash", os.path.join(E32C_DIR, "build.sh")], capture_output=True, text=True,
                       env=dict(os.environ, E32C_BASE=hex(E32C_BASE), E32C_ROLE=ROLE))
    if r.returncode:
        die("engine32c build failed:\n" + r.stdout + r.stderr)
    blob = open(os.path.join(E32C_DIR, "build", "engine32c.bin"), "rb").read()
    syms = {}
    for line in open(os.path.join(E32C_DIR, "build", "engine32c.map")):
        va, name = line.split()
        syms[name] = int(va, 16)
    blob = fill_dual_table(blob, syms)
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    coff = pe + 4
    nsec = struct.unpack_from("<H", d, coff + 2)[0]
    opt = coff + 20
    sect = opt + struct.unpack_from("<H", d, coff + 16)[0]
    hdr = sect + nsec * 40
    if any(d[hdr:hdr + 40]):
        die("P6: no free section header slot")
    falign = struct.unpack_from("<I", d, opt + 0x24)[0]
    raw_off = (len(d) + falign - 1) & ~(falign - 1)
    raw_size = (len(blob) + falign - 1) & ~(falign - 1)
    vsize = (len(blob) + 0xFFF) & ~0xFFF
    rva = E32C_BASE - IMAGE_BASE
    d[hdr:hdr + 40] = b".iw4c\0\0\0" + struct.pack("<IIIIIIHHI", vsize, rva, raw_size, raw_off, 0, 0, 0, 0, 0xE0000060)
    struct.pack_into("<H", d, coff + 2, nsec + 1)
    old_len = len(d)
    d.extend(b"\0" * (raw_off - len(d)))
    d.extend(blob + b"\0" * (raw_size - len(blob)))
    struct.pack_into("<I", d, opt + 0x38, max(struct.unpack_from("<I", d, opt + 0x38)[0], rva + vsize))
    note(hdr, 40, "PE header: new section .iw4c (injected code, source: engine32c/)")
    note(coff + 2, 2, "PE header: NumberOfSections")
    note(opt + 0x38, 4, "PE header: SizeOfImage")
    note(old_len, len(d) - old_len, f"appended section .iw4c @ {E32C_BASE:#x}: compiled engine32c code + data")
    print(f"P6  .iw4c @ {E32C_BASE:#x} ({len(blob):#x} bytes, {len([k for k in syms if k.startswith('_e32_')])} e32 symbols)")
    for va, old, stub, what in P6_HOOKS:
        fo = va - IMAGE_BASE
        ob = bytes.fromhex(old)
        if bytes(d[fo:fo + len(ob)]) != ob:
            die(f"P6 {va:#x} {what}: expected {old}, found {bytes(d[fo:fo + len(ob)]).hex()}")
        if len(ob) < 5 or stub not in syms:
            die(f"P6 {va:#x}: bad hook definition")
        rel = syms[stub] - (va + 5)
        d[fo:fo + len(ob)] = b"\xE9" + struct.pack("<i", rel) + b"\x90" * (len(ob) - 5)
        note(fo, len(ob), f"{va:#x} hook: jmp {stub} ({what})")
        print(f"P6  {va:#x} -> {stub} {syms[stub]:#x}: {what}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(MODDED, "iw4x.exe.orig32"))
    ap.add_argument("--dst", default=os.path.join(MODDED, "iw4x.exe"))
    ap.add_argument("--alt-layout", action="store_true",
                    help="loader/gen_tables.py only: same build with .iw432 at +0x10000000 and .iw4c at "
                         "+0x40000000, diffed against the normal build to find every slot that points into them")
    ap.add_argument("--role", default="server", choices=("server", "client"),
                    help="client = public player build without the server-side changes (hosts <= 18 players)")
    ap.add_argument("--manifest", help="also write a release manifest (every changed byte + reason) to this JSON file")
    a = ap.parse_args()
    apply_role(a.role)
    if a.alt_layout:
        global SECTION_VA, E32C_BASE
        SECTION_VA += 0x10000000
        E32C_BASE += 0x40000000

    d = bytearray(open(a.src, "rb").read())
    if hashlib.md5(d).hexdigest() != PRISTINE_MD5:
        die(f"{a.src} is not the pristine 18-client exe (md5 {PRISTINE_MD5})")

    vsize = layout()
    p1_section(d, vsize)
    p2_relocate(d)
    p3_cvars(d)
    p4_sizes(d)
    global PRISTINE
    PRISTINE = bytes(open(a.src, "rb").read())
    p5_code(d)
    p6_inject(d)
    svs = [r for r in RELOCS if r["name"] == "svs_clients"]
    if svs and struct.unpack_from("<I", d, 0x401AC4 - IMAGE_BASE)[0] != svs[0]["new_lo"]:
        die("G1 (_e32_ui_party) expects the relocated svs_clients base at 0x401AC4")

    if os.path.abspath(a.dst) == os.path.abspath(a.src):
        die("refusing to overwrite the pristine source")
    tmp = a.dst + ".tmp"
    open(tmp, "wb").write(d)
    os.replace(tmp, a.dst)
    print(f"\nwrote {a.dst}  md5 {hashlib.md5(d).hexdigest()}")
    if a.manifest:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools-re"))
        import manifest_lib
        manifest_lib.write_manifest(a.manifest, PRISTINE, d, WRITES, dict(
            file="iw4x.exe", role=ROLE, build="engine32 r23" + ("-player" if ROLE == "client" else ""),
            official="iw4x.exe from IW4x r5154 (unchanged since r5121; same bytes as the IW4x release)"))


if __name__ == "__main__":
    main()
