# IW4x-32 → IW4x: how to merge 32-player support into the main game

This section is for the **IW4x developers**. It describes **every change** IW4x-32 makes, why it's needed, and
how to bring it into `iw4x-client` with as little work as possible. Every claim below is backed by a
machine-readable table:

| File | Contents |
|---|---|
| [`engine_patches.json`](engine_patches.json) | all **iw4x.exe** changes, against pristine r5154 `iw4x.exe`, MD5 `9c42ffa4f7aefd08fd501b40f5e41eab`, base `0x400000`: 14 arrays + 701 operand sites, 6 size constants, 85 code patches (27 dual), 14 hooks |
| [`dll_patches.json`](dll_patches.json) | all **iw4x.dll** changes against the r5154 release DLL: 9 engine pointers, 8 arrays, 27 constants |
| [`../server/source/engine32c/`](../server/source/engine32c) | the injected C/asm: layout switch, lag compensation, hook stubs |
| [`../server/source/manifest_*.json`](../server/source) | the byte-exact diff of our binaries, every changed byte with its reason |
| [`build/`](build) | the tools that make our binaries from the official ones (`patch_engine.py`, `patch_dll.py`) |
| [`reference/loader/`](reference/loader) | a working in-memory patcher (C) that applies the engine tables at start-up (written for r5121: regenerate `tables.h` with `gen_tables.py` for r5154) |

Every entry is tagged **`role: client`** (players need it) or **`role: server`** (only needed to host more
than 18 slots).

## The short version

1. **DLL (`iw4x-client` source):** set `Game::MAX_CLIENTS` to **32** (`Game/Functions.hpp`). Everything in IW4x
   that is sized or bounded by it then follows: bots, voice, clan tags, card titles, the server-browser filter,
   status/admin paths. The details are under *DLL* below.
2. **Engine (`iw4mp`):** the game binary itself is sized for 18 everywhere. IW4x already patches the engine at
   start-up, so this is one more component. It needs to:
   - allocate the enlarged arrays and rewrite their operands (`relocation_operands`);
   - apply the byte patches (`code_patches`, `size_constants`, `cvar_domains`);
   - install the hooks;
   - port `engine32c/` into C++.

   `reference/loader/loader.c` does all of this from generated tables in about 240 lines. It's the closest
   template for an `iw4x-client` component.
3. **Compatibility:** one client must keep working on stock 18-player servers. The engine's player/body entity
   layout differs, and 27 code sites are switched at connect time (`dual: true`). See *Compatibility* below.

## Engine changes (iw4x.exe)

### 1. Per-player arrays: allocate bigger copies, rewrite every reference
| Array | Old range | New size | Role | Note |
|---|---|---|---|---|
| `svs_clients` | `0x31D9390` +18×`0xA6790` | 32× | server | 115 operands, 33 of them with *folded* offsets (`&svs.clients[i].field`) |
| `level_bgs` | `0x19BD680..0x1A45D20` | +14×`0x52C` | server | bgs_t is `0x886A0` bytes (IW4x's `Structs.hpp` says `0x82950`: wrong). 2 `g_entities` loop sentinels excluded |
| `g_clients` | `0x1A45E10` +18×`0x366C` | 32× | server | ends exactly at `level`; `level.clients` points here |
| `sortedClients` | `level+0x3E4` | 32×4 | server | `CalculateRanks` overran into `voteString` |
| `post_cg_globals` | `0x8EE4B8..0x8F37D0` | moved | client | moved out of the way so `cg_s.clientinfo[18]` can grow **in place** to [32] |
| `cg_tail` | `0x8ED4C8..0x8EE4B8` | shifted +`0x4868` | client | absolute **and** cg-relative operands (21 base-relative displacements) |
| `cg_scores` | `0x863C38` | 32×`0x28` | client | + 2 one-based sentinels |
| `compass_actors` | `0x7D7FA8..0x7D85C0` | 40×`0x3C` | client | minimap: players 0..31, bodies 32..39 |
| `ui_playerNames` / `ui_playerClientNums` | `0x62E4BD4` / `0x62E5054` | 32 | client | `UI_BuildPlayerList` overflow |
| `cl_ring44` | `0x62C8228` | 32×`0x44` | client | per-player ring buffer, overflowed into `loc_language` |
| `cl_voiceDecoders` / `cl_voiceTalkTime` / `snd_voiceBufPool` | `0x64A39E0` / `0x64A3A28` / `0x1AA5E48` | 32 / 32 / 33 | client | phantom "talking" icons and a crash with talker ≥ 18 |

Each operand in `relocation_operands` gives the instruction VA, the operand VA, and old and new values. It also
gives `array` + `new_array_offset`:

    operand = base_of_new_array + new_array_offset

`fixed: true` entries are absolute: `cg_tail` stays inside `cg_s`. **Pitfall we hit:** a compiler-folded biased
index, e.g. ASCII `'0'`×4 folded into the displacement, can make a reference look as if it points inside a
relocated array when it doesn't. The `excluded_sites` lists hold those (3 in `post_cg_globals`), and the build
aborts if any count differs from what's expected.

### 2. Constants and checks (`size_constants`, `code_patches`, `cvar_domains`)
- **Domains:** `sv_maxclients` / `ui_maxclients` / `party_maxplayers` 18 → 32.
- **Sizes:** memset sizes of the grown arrays, and the `level.clients` byte loop bound.
- **Entity layout:** players 0..31, spare 32..35, body clones 36..43 (stock: 18..25), first free entity 44 (stock 26).
- **"entnum < 18 means a player" checks:** cg interpolation, eye position, crosshair names, pmove/missile traces,
  `showToPlayer`, the archive.
- **Snapshots:** `clientStates[18]` → 32 inside `snapshot_s`; the entity cap goes 768 → 761 so the struct size
  stays the same.
- **Compass:** strides 26 → 40 actors per local client, loop counts, corpse actor base.
- **Renderer skinned-vertex cache:** `0x480000` → `0x900000`. With 32 players, models went invisible.
- **Host migration:** disabled, because its state holds 18. The match ends instead.

### 3. Hooks + injected code (`hooks`, `engine32c/`)
| Hook | Purpose |
|---|---|
| `SV_SendClientMessages` ×3 | `needsSnapshot[18]` lived on the stack → a global [64] |
| `G_AntiLagRewindClientPos` / `Restore` | lag compensation rewritten for 32 clients (`antilag.c`) |
| `SV_UserinfoChanged`, `SV_DropClient`, `Session_GetXuidForSlot`, `Session_SetClientAddress`, PartyHost teardown | `SessionData.users[18]` / lobby members: slots ≥ 18 are kept out of the party/session tables (a human in slot 23+ used to corrupt the next session object) |
| `SV_SpawnServer`, `CL_Init`, `SV_DirectConnect`, `CG_ParseServerinfo` | compatibility: marker dvars, the unpatched-client refusal, the layout switch (`compat.c`) |

## DLL changes (iw4x.dll → iw4x-client source)
All of these become source edits. Almost all of them follow from **`Game::MAX_CLIENTS = 32`**:

| Component | Change | Role |
|---|---|---|
| `Bots` | `g_botai[MAX_CLIENTS]`, `spawnBot` clamp | server |
| `Voice` | `VoicePackets` / `VoicePacketCount` / `MuteList` (server relay) | server |
| `Voice` | `S_PlayerMute`, `CL_VoicePacket` talker bound, `Voice_UnmuteMember` bound | client |
| `ClanTags` | `ClientState[MAX_CLIENTS][5]`; send loop (server) + parse loop (client) | both |
| `CardTitles` | `CustomTitles[MAX_CLIENTS][18]`: send (server), parse / lookup / memset (client) | both |
| `ServerList` | the "more than 18 players are faking" filter → `MAX_CLIENTS` | client |
| `ServerInfo` | getstatus player list, bot count | server |
| `Download` | `/info` player list | server |
| `Bans`, `Chat` | slot bounds for ban / sayTo / tellTo | server |
| r5154 per-client flag (`give`/ammo command) | `byte[18]` → 32 | server |
| `Updater` | **not a limit**: the HTTP thread set `cl_updateAvailable` off the main thread, which crashed in `va()` (null TLS, `0x4EC749`). IW4x-32 just never sets it; the real fix is to set it on the main thread | client |

The engine addresses the DLL hard-codes (`Game::svs_clients`, `level_bgs`, the cg/UI arrays) must point to the
moved arrays: `engine_pointers` in `dll_patches.json`. In source, read them from wherever the engine component
allocated them.

## Compatibility: one client for stock and 32-player servers
- **Marker dvars:** clients register `iw4x32 = 1` (USERINFO | ROM). Servers with more than 18 slots register
  `sv_iw4x32 = 1` (SERVERINFO).
- **Server side:** with more than 18 slots, `SV_DirectConnect` refuses remote clients without `iw4x32\1` (bots
  and loopback are exempt), with a message. With 18 or fewer, the server keeps the **stock** entity layout and
  admits everyone.
- **Client side:** `CG_ParseServerinfo` reads `sv_iw4x32`. On stock servers the 27 `dual` sites are written back
  to their original bytes (bodies at 18..25, "player" means entnum < 18); on 32-player servers our bytes are
  restored. `e32_dual_tab` in `compat.c` holds the original bytes, which the build fills in from the pristine exe.

In an IW4x-native version this could be a protocol bump instead. Our goal was to stay connectable to stock
r5154 servers with one set of files.

## Testing done
All tests ran under Wine on Linux: Ubuntu, a real AMD GPU client, and Wine dedicated servers.
- 31 bots + 1 human for hours.
- AC-130, chopper gunner and predator for players 19-32.
- Minimap with 15/15 teammates.
- Scoreboard, calling cards, voice.
- Real players joining from slots 19-32.
- The patched client on stock public r5154 servers.
- The stock client refused on 32-slot servers and admitted on 18-slot ones.
- Dedicated servers running for days with 32 players.

**Known limits:**
- End-of-match stats record players 1-18 only. This hasn't been traced yet.
- Under very heavy killstreak use, one client crash in three soak runs (not reproduced).
- The game logic runs on one CPU core, and 32 players cost more per frame than 18: a host needs good single-core speed.

## Build tools (`build/`)
- `patch_engine.py --role server|client`: builds iw4x.exe from the pristine exe, aborting on any reference-count
  or original-byte mismatch.
- `patch_dll.py --base r5154 --role server|client`: the same for iw4x.dll.
- `--manifest` writes the byte manifest.
- `make_integration_tables.py` writes the two JSON tables here.

The scripts expect the official files at the paths set at their top, and `engine32c/build.sh` needs
i686-w64-mingw32-gcc.
