# QWEN_REPORT — v2.0 client does not come back after a map change

Task: `iw4x32/tasks/map_change_rejoin.md`. Branch `fix/iw4x32-map-change`. Round 1.

## 0. Plan / state

- Reproduce with the live test (`--bots 8 --client --minutes 5 --map-change-at 2`), read the **client** console
  (the test only prints the server's) before changing code.
- The CHECK commands are the build and the live test; both exist, so the deliverable is in place from the start.
- Client console capture: the test script lives outside this worktree and the round rules forbid editing files
  outside it, so the diagnosis runs use a scratch copy of it (`.scratch/aiboi_cli.py`) that does the same thing
  plus dumps the client's `main/console_mp.log` and greps the server log for the IW4x-32 reject line. The CHECK
  command itself is run unchanged.

## 1. Evidence from the live test (baseline build, unmodified code)

Run A - the CHECK form `--bots 8 --client --map-change-at 2` (scratch runner, 10 s polls):

* 8 bots + the client: the client lands in **slot 8**, not >= 18, because the test spawns the bots first and the
  client takes the first free slot. The CHECK's pass rule needs `client_slot >= 18`, so with `--bots 8` it can
  never pass whatever the code does - see BROKEN CHECK at the top.
* Nothing crashed, the server stayed up, the client was still in the server after the "map change".

Run B/C - `--bots 28 --client --map-change-at 2` (client in slot 28, `-stdout` so its console is captured):

* Before the change: 29 players, human in slot 28. `rcon map_rotate` -> the client console prints
  `Server changing map mp_rust, gametype dom`, it reloads `mp_rust_load`/`mp_rust` and is back in the game;
  status keeps showing 29 players with the human in slot 28.
* **The server console shows no second level restart at all**: no second `------ Server Initialization ------`,
  no second `iw4x32: 32-slot server - ...` line, no `Client N connecting`, no new
  `Going from CS_FREE to CS_CONNECTED` for the human's guid. The bots are re-created (bot28..bot55 take slots
  0..27) but the human's client slot 28 is never freed and never re-connected.
* Reason: the test server's playlist (`userraw/server.cfg`: `addGametype dom`, `addMap mp_rust`) holds exactly
  one map, so `map_rotate` rotates to the *same* map - the engine does not run `SV_SpawnServer`, nobody gets
  disconnected, and the client only reloads the map locally. The live report's rotation (`ShutdownGame`, then
  `Server Initialization`, then our `iw4x32: 32-slot server` line) is a real level change through
  `SV_SpawnServer`, which drops every client. So the CHECK's `--map-change-at` step does not reproduce the bug.

Next: force a real level change (`rcon map mp_broadcast`) and read both consoles.

### What the code does today (client side, map change)

- `iw4x.dll` registers the `iw4x32` userinfo dvar from the `CL_Init` hook (`_e32_cl_init_hook`, 0x4D9571) - once
  per process, not per connect.
- `CG_ParseServerinfo` hook (`_e32_cg_si_hook`, 0x4CCF44) reads `sv_iw4x32` and calls `SetLayout()`; `SetLayout`
  returns early when the layout is already what is asked for, so a reconnect re-parsing serverinfo is a no-op.
- `SV_DirectConnect` hook (`_e32_dc_check`) rejects any remote client whose userinfo lacks `iw4x32\1`, printing
  `rejected connect: client without the iw4x32 (32-player) build` in the server console.
- IW4x itself follows a server map change through `Maps::RotateCheckStub` (hook at 0x5AA91C): if the new map is
  installed and hashed OK it calls the engine's rotate-map routine (0x487C50) on the client, otherwise it
  disconnects and re-`reconnect`s through the IW4x container/party path.

## 2. What actually reproduces: the client leaves on its own, `@XBOXLIVE_PARTYENDED`

The live report's client console (`userraw/console_mp.log` from the v2.0 test box) ends with

```
[    665018] Disconnecting from 00000000.000000000000:0 (@XBOXLIVE_PARTYENDED) at time 665018
```

- nothing before it, no error, no crash dump - the client walks out of the game by itself and goes back to the
  menu (`CL_Live_StartPrivateParty` right after). From the server's side the client then goes quiet and is
  dropped `GAME_DROPPEDFORINACTIVITY`, which is what the server log shows.
- the host address is `00000000.000000000000:0`: the client's own party has no host address recorded.

Reproduced with our own runner (`.scratch/live_repro.py`: stock `iw4x.exe` + this branch's `iw4x.dll`, 32 slots,
`+map_rotate`, 28 bots, one human, `-stdout` on both):

| run | bots | human slot | scorelimit | level restart | result |
|---|---|---|---|---|---|
| live1 | 28 | 28 | 200 | none seen | `@XBOXLIVE_PARTYENDED` at client time **479 s** |
| live2 | 28 | 28 | 200 | `map_restart` at 2 min | `@XBOXLIVE_PARTYENDED` at **427 s** |
| expE  | 28 | 28 | 999999 | none | **clean at 643 s** |
| expF  | 28 | 28 | 200 | none | `@XBOXLIVE_PARTYENDED` at **720 s** |
| expA  | 8  | **0**  | 200 | none | **clean at 714 s** |

So the trigger is **the human sitting in a slot >= 18**, not the map change: with 8 bots the human is in slot 0
and survives 12 minutes, with 28 bots the human is in slot 28 and walks out after 7-12 minutes (the time
varies; a level restart seems to bring it sooner). The map change in the live report is when the box *noticed*
the client was gone.

Why: the stock engine sizes the XLive session/party layer for 18 (`ClientInfo users[18]` at `sessionState+0x230`,
`RegisteredUser internalRegisteredUsers[18]`, `PartyMember partyMembers[18]` at `party+0x1D8`, and the member
loops are hard-bounded `i < 0x12`). IW4x-32 does not enlarge those - it keeps slots >= 18 out of them with five
hooks (`SV_UserinfoChanged` 0x401AAD, `SV_DropClient` 0x4C17DC, `Session_GetXuidForSlot` 0x487C10,
`Session_SetClientAddress` 0x49ABB0, PartyHost member teardown 0x4D3D00). The client's own party bookkeeping
indexes those tables with the *game* clientNum, so for a client in slot 28 its own entry is never written -
`Session_SetClientAddress` (0x49ABB0, called from the party frame code at 0x5B03AC and 0x5B1C31/0x5B1C4A) is
where its address would land. The party host address stays zero, the host goes "gone", and the engine's
host-timeout handler at **0x5028B0** takes its silent branch
(`systemlink != 0 || *(cl + 0x1848 /*partyId*/) == 1` -> `CL_Drop("@XBOXLIVE_PARTYENDED")`, no console print).

Probe: a temporary hook on 0x5028B0 (enabled by an `iw4x32-probe` file next to `iw4x.exe`) prints the caller of
that handler - see below.

---

# Previous round report — IW4x-32 engine component

**Result: a stock `iw4x.exe` (r5154, MD5 `9c42ffa4f7aefd08fd501b40f5e41eab`, untouched on disk) plus our
`iw4x.dll` runs a 32-player dedicated server with 31 bots, no crash.** The DLL rewrites the closed-source
engine in memory at start-up, the way IW4x already patches the engine for its own fixes.

Branch: `feat/iw4x32-engine` (worktree). Nothing pushed.

---

## 1. Deliverables

| file | what it is |
|---|---|
| `iw4x32/tools/gen_tables.py` | `iw4x32/reference/engine_patches.json` → `src/Components/Modules/IW4x32Tables.hpp`. Deterministic, no binary input: it only reads the JSON. |
| `src/Components/Modules/IW4x32Tables.hpp` | generated & committed: 14 arrays, 701 relocation operands, 8 cvar-domain byte patches, 6 size constants, 85 code patches (27 `dual`), 14 hooks, 990 bytes of patch pool. |
| `src/Components/Modules/IW4x32.hpp` / `.cpp` | the component (803 lines): verify → allocate → rewrite operands → apply patches → install hooks → re-point the DLL's own engine pointers; plus the dual 18/32 layout switch and the lag-compensation port. |
| `iw4x32/tools/check_tables.py` | fails unless the generated header holds exactly the entries of `engine_patches.json`: counts per kind **and per role**, every address, every byte string, the dual flags, and the `IW4x32_*Count` constants. |
| `iw4x32/tools/smoke32.py` | runs `tools-re/run_server.py` with `--exe iw4x.exe.orig32 --dll <this build> --maxclients 32 --bots 31 --duration 240`; fails unless the map came up, 31 clients show in rcon `status`, nothing crashed, and the console carries an `iw4x32:` line (only the DLL can have produced it — the exe on disk is the stock one). |

Checks:

```
bash $HOME/Projects/IW4x-32/tools-re/build_iw4x_fork.sh . Release    # ~5 min, MSVC under Wine
python3 iw4x32/tools/check_tables.py                                # ok - 14 arrays, 701 operands, 8 cvar domains, 6 size constants, 85 code patches, 14 hooks match engine_patches.json
python3 iw4x32/tools/smoke32.py                                     # ok - map up, 31 clients in status, no crash
```

## 2. How the component works

Registered in `Loader::Initialize()` directly after `Logger` — component constructors run from `DllMain`'s
entry-point hook, before any engine game code executes, so patching there is safe.

1. **All-or-nothing verification.** The main module must be at `0x400000`, its MD5 must be the r5154 one, and
   every byte the tables expect (hook prologues, patch sites, cvar domains) must already be there. If any of
   it differs, **nothing is written**. A file named `iw4x32-disable` next to `iw4x.exe` skips patching too.
2. **Arrays.** One `VirtualAlloc` holds the 14 enlarged arrays (`svs_clients` 0x14CF200, `g_clients` 0x6CD80,
   `bgs`, `cg`, `clientInfo` tail, ui/cg/voice/sound arrays). Allocation is all-or-nothing with cleanup.
3. **701 operands.** Each entry stores `new_array_offset`; at run time the new value is
   `alloc_base + offset` (the 277 `cg_tail` ones are `old + 0x4868`, the shift `cg_s` grew by). Nothing about
   our allocation layout is baked into the header, and sentinels just before an array (`0xffffffd8`) fall out
   of the same u32 arithmetic.
4. **Size constants, cvar domains, code patches.** 6 numeric constants (`0x12`→`0x20` style), 8 `push 0x12`
   cvar-domain sites, 85 code patches. The 27 `dual` patches are recorded so they can be flipped back to the
   stock 18-player bytes.
5. **Hooks.** 14 sites, `Utils::Hook(va, stub, HOOK_JUMP).install()->quick()`, stubs are
   `__declspec(naked)` in an anonymous namespace — a direct port of `engine32c/stubs.S` (needsSnapshot
   widening, party/session slot guards, the `iw4x32` marker, the connect check, the layout switch).
6. **Dual layout.** The `SV_SpawnServer` hook registers the `iw4x32` (userinfo) and `sv_iw4x32` (serverinfo)
   dvars and selects the layout for the 27 dual sites; `SV_DirectConnect` refuses a client that does not send
   `iw4x32\1` (same reject path the engine uses for "migration in progress"); `CG_ParseServerinfo` reads the
   server's `sv_iw4x32` and switches the same 27 sites so one client build joins both stock and 32-player
   servers.
7. **Lag compensation.** `engine32c/antilag.c` ported as two cdecl functions that replace
   `G_AntiLagRewindClientPos` (0x4C1120) and `G_AntiLagRestoreClientPos` (0x440040) outright: 32-entry
   position/angle/valid buffers, one global store instead of the engine's 0x1C4 caller-stack store (which
   would run over the caller's return address at 32 clients), and the archive-frame decoder's 18 cut-off
   widened to 32. Transcribed line by line from the reference; only the bounds changed.
8. **The DLL's own pointers.** `Game::svs_clients`, `Game::level_bgs`, `Game::cgMedia` are re-pointed at the
   new arrays; `IW4x32::PlayerNames()` / `PlayerClientNums()` feed `Vote.cpp` and `Voice.cpp`;
   `CardTitles.cpp` needs nothing because its bound comes from `Game::MAX_CLIENTS` (already 32).

## 3. Things worth knowing (found the hard way)

* **`/LTCG` constant-folds the `Game::` address globals.** `client_s* svs_clients = (client_s*)0x31D9390;`
  gets propagated into code, so re-pointing the variable would change nothing. The fix is a volatile seed:
  `static volatile DWORD s_svs_clients_stock = 0x31D9390; client_s* svs_clients = (client_s*)s_svs_clients_stock;`
  After every build, scan the DLL: there must be **zero** leftover `0x31D9390` / `0x19BD680` / `0x8EE4B8` /
  `0x8ED4C8` immediates in `.text` (verified: 0, 0, 0, 0; the only `0x62E4BD4`/`0x62E5054` left are the
  not-patched fallbacks inside the two accessors).
* **`Utils::Hook(...).install()->quick()` is not optional.** `Hook::~Hook()` uninstalls; `quick()` clears the
  *static* `installed` flag so the temporary's destructor leaves the patch in place.
* **A stub may not touch a register or a flag the resumed engine code still needs.** The first 240 s run died
  at `0x487C25` inside `Session_GetXuidForSlot`: the stub used the codebase's `mov eax, ADDR; jmp eax` idiom
  to get back, which overwrote `eax` — and `eax` *was* the slot the resumed code indexes with
  (`lea ecx,[eax+0xA] … cmp [edx+esi*8],0`). Every stub now hands control back with
  `jmp dword ptr [s_back_…]`, an indirect jump through a `.data` cell: no register, no flag, no ±2 GB range
  worry. `SscmSet`/`SscmTest` resume on a `je` whose flags come from an earlier engine `cmp`, so the stubs
  must not disturb the flags either.
* **`engine32c/stubs.S` is stale in places** (its hook VAs come from an older engine). `engine_patches.json`
  is authoritative: all 14 hook VAs and their `replaced` bytes were checked against the pristine exe with
  capstone before writing the stubs.
* **Minidumps are empty under Wine.** The component installs a first-chance vectored handler that prints
  `iw4x32: exception <code> at <addr>` plus the registers to stderr and keeps searching — that is what turned
  "the server vanished" into a single instruction address. (IW4x's own `Exception` component is untouched.)
* `version.h` / `version.hpp` are gitignored and generated by premake's `setversion`; the build script strips
  prebuild commands, so they are copied from the main checkout before building.
* MSVC: `__declspec(naked)` only on definitions (not forward declarations), `new` is not a field name,
  `call 0xADDR` needs `mov ecx, 0xADDR; call ecx`.

## 4. Test evidence

| run | setup | outcome |
|---|---|---|
| `20261012-230655-iw4x32-quick` | stock exe, this DLL, 32 slots, 31 bots, 90 s | map up, **31 clients in `status`**, no crash |
| `20261012-231001-iw4x32-full` | same, 240 s | crashed 60-87 s in (empty minidump) → root-caused to the `eax` clobber |
| `20261012-232449-iw4x32-crash1` | same, with the first-chance reporter | `exception C0000005 at 00487C25` — `Session_GetXuidForSlot` |
| `20261012-233922-iw4x32-fix1` | fixed stubs, 240 s | **map up, 31 clients in status, no crash** |
| `20261012-235445-iw4x32-final` | comment-only changes since fix1, 240 s | **ok** |
| `20261013-000959-iw4x32-off` | `iw4x32-disable` next to `iw4x.exe`, 18 slots, 17 bots, 60 s | `IW4x32: iw4x32-disable found - not patching`, map up, no crash |
| `20261013-001113-iw4x32-final2` | final source (hook-stub names verified up-front), 240 s | **ok — map up, 31 clients in status, no crash** |

`check_tables.py` was also shown to be sensitive: a wrong address, a dropped operand, a wrong byte string or a
wrong count each makes it exit 1.

## 5. Not covered / follow-ups

* Only the **dedicated server** path is smoke-tested. The 32-player *client* (joining, HUD, voice, scoreboard,
  the `CG_ParseServerinfo` switch and the 27 dual sites in 18-player mode) has no automated test yet — the
  natural next smoke is a client connecting to this server and a second server left at 18 slots.
* Bots only: no real client, no votes, no map rotation, no `SV_RestartServer`.
* The dual switch is exercised only in the 32-player direction in these runs; the 18-slot run above only
  proves the component stays out of the way when it is switched off by the file.
* The MD5 / byte-level fail-safe (a non-r5154 exe must not be touched at all) is implemented but has no run
  behind it — it needs a deliberately wrong exe to try.
* The first-chance exception reporter is new behaviour in a shipped DLL; keep it if the team likes the extra
  line, drop `AddVectoredExceptionHandler(1, &CrashReport)` if not.

---

# QWEN_REPORT — round 2: the IW4x-32 player kit, `latest.json`, the release workflow

**Result: `iw4x32/release/` is a complete v2.0 kit whose only installed file is `files/iw4x.dll`; `latest.json`
carries its version and the SHA-256 of all 15 kit files; `iw4x32-release.yml` builds and publishes it on a `v*`
tag; `check_kit.py` passes and is sensitive to every rule it claims.** The installers were *run* — the Linux
ones directly, the Windows ones under Wine cmd with real SHA-256 hashing — against fake game folders. That run
found a real bug in `Install IW4x-32.bat` (below). The dll that ships in the kit is the one that passed round 1's
240 s / 31-bot server smoke. A Windows client with it has still not been played.

Branch `feat/iw4x32-kit` (worktree of `feat/iw4x32-engine`). Nothing pushed. Round 1 (the engine component
itself) is reported above.

---

## 1. Deliverables

| file | what it is |
|---|---|
| `iw4x32/release/` | the kit players download: `Install IW4x-32.bat`, `Uninstall IW4x-32.bat`, `Play IW4x-32.bat`, `Play IW4x-32 (no update).bat`, `Play IW4x-32 (IW4x launcher, no file check).bat`, `install-linux.sh`, `uninstall-linux.sh`, `play-linux.sh`, `iw4x32_update.py` + `iw4x32_update.ps1` (auto-update before the game starts), `README.txt`, `CHANGES.txt`, `AI_CREDITS.txt`, `SHA256SUMS.txt`, `files/iw4x.dll` |
| `latest.json` (repo root) | `version: v2.0`, `iw4x: r5154`, the official r5154 `iw4x.exe`/`iw4x.dll` hashes, `base_url` pointing at this tag's `iw4x32/release/` on raw.githubusercontent, and the SHA-256 of every kit file |
| `.github/workflows/iw4x32-release.yml` | `v*` tag → build Release/Win32 on windows-2022 (same steps as `build.yml`) → `make_latest.py --dll <built>` → `check_kit.py` → zip the kit as `IW4x-32-<tag>.zip` → draft GitHub Release with the zip, `iw4x.dll` and `SHA256SUMS.txt` |
| `iw4x32/tools/make_latest.py` | puts the built dll in the kit, syncs the `OURS_DLL` constant the installers verify against, writes `SHA256SUMS.txt` and `latest.json` |
| `iw4x32/tools/check_kit.py` | nine checks over the kit, the manifest, the line endings and the workflow (see 4) |
| `iw4x32/tools/make_version_h.py` | `src/version.h` / `version.hpp` for the Wine build, with the same revision rule as `premake5.lua` |
| `iw4x32/tools/{sh_test,bat_test,upd_test}.sh`, `mini_certutil.c` | the tests in section 5 |

## 2. What changed against the v1.x kit

The old kit patched `iw4x.exe` (a loader that started the game with the 32-player arrays already in place) and
shipped `iw4x.exe` + `iw4x.dll`. **v2.0 installs one file.** The exe stays the official IW4x one, because the
engine work now happens inside `iw4x.dll` at start-up (round 1). Consequences the kit has to handle:

* Installers verify the game's `iw4x.dll` is the official r5154 file (SHA-256) before touching anything, back
  it up to `IW4x-32/backup/`, install ours, then re-hash what landed.
* A player arriving from v1.x has a patched `iw4x.exe`. Both installers and the updater detect it (hash
  `2609c268…`) and put the official exe back from `backup/` — the only way the kit writes `iw4x.exe` at all.
* The IW4x launcher's own file check puts the official dll back, so the kit ships launchers that avoid it, and
  the updater repairs the dll on every start.
* Uninstall restores both files from `backup/`.

## 3. Invariants, and how they are checked

| invariant | how it is enforced |
|---|---|
| nothing but `files/iw4x.dll` is installed into the game folder | `check_kit.py` fails on any `files/iw4x.exe`, and on any line in an installer/updater that copies *to* the game's `iw4x.exe` unless the same line mentions `backup` — the restore path is the only legal one |
| the kit's bytes are the bytes players download | `.gitattributes` marks `iw4x32/release/**` as `-text`: git stores them verbatim, `.bat`/`.ps1`/`.txt` stay CRLF, `.sh`/`.py` stay LF, and raw.githubusercontent serves exactly what `latest.json` hashed |
| the installers' `OURS_DLL` matches the kit dll | it is a `PENDING` placeholder in the sources; `make_latest.py` fills it in, `check_kit.py` re-checks it |
| every download is what the manifest says | the updater stages downloads, hashes each one against `latest.json`, and swaps nothing if one is off (proved in 5) |
| the DLL must not nag players about updates | `REVISION_STR` has to read `r5154`, see 6 |

## 4. `check_kit.py`

Passes on the real kit. Its sensitivity was shown on a scratch tree — each of these makes it exit 1: a file
whose bytes no longer match its hash in `latest.json`; a hash missing from the manifest; a `files/iw4x.exe`; an
installer line copying to `iw4x.exe` without `backup`; a stale `OURS_DLL`; a README/CHANGES version that
disagrees with the manifest; a kit file whose CRLF/LF ending is wrong; a workflow that does not trigger on
`v*`.

## 5. Tests actually run

| test | what it does | result |
|---|---|---|
| `sh_test.sh` | `install-linux.sh` / `uninstall-linux.sh` against a fake game folder whose official/v1.x hashes are patched into the scripts | ok — official dll checked and backed up, ours installed, v1.x exe restored from `backup/`, re-run says "already installed", modded dll refused with nothing changed, missing v1.x backup stops, a folder with no game stops |
| `bat_test.sh` | the same cases for the Windows `.bat` files, under **Wine cmd**, with `mini_certutil.exe` compiled by the project's own MSVC standing in for Wine's no-op `certutil` | ok — same results; **this is where the `goto :end` bug surfaced** |
| `upd_test.sh` | `iw4x32_update.py` against a fake game folder and a `latest.json` served from a local directory: v2.0 → v2.1 update, then a no-op run, then the launcher putting the official dll back, then a tampered download | ok — installs only the dll, restores the v1.x exe, backs up the official dll, repairs, and refuses the tampered download without changing a byte |
| `check_kit.py` / `git-privacy-check work` | the kit and the whole tree | ok / clean |
| `smoke32.py` (round 1's) | the 240 s / 31-bot dedicated-server smoke, run with **the dll that ships in the kit** | ok — map up, 31 clients in `status`, no crash |

## 6. Two things worth the team's attention

* **`REVISION_STR` was wrong for a fork.** premake's `getRevisionNumber()` used `git rev-list --count HEAD`:
  56 on this shallow worktree, 5163 on a full clone. IW4x's `Updater.cpp` compares that against the newest
  release tag, so every player of our kit would have seen "an update is available" forever. It now takes the
  nearest `r*` tag (`git describe --tags --abbrev=0 --match r[0-9]*`) → **r5154**, the release the DLL is built
  against. Upstream's own releases are unaffected: their tag *is* the commit count.
* **A called batch routine must not `goto :end`.** `Install IW4x-32.bat` printed "STOPPED: nothing was changed"
  for a v1.x exe without a usable backup and then — because `goto` inside a `call`ed label returns to the
  caller — carried straight on and installed `iw4x.dll`. Now `exit /b 1` + `call :restore_v1_exe || goto :end`.
  Worth remembering for every other `.bat` in this repo.

## 7. Not covered

* **No Windows client has been played with this kit.** The `.bat` files ran under Wine cmd with real hashing and
  stock cmd semantics; the DLL itself was smoke-tested as a dedicated-server module in round 1. The client path
  (joining a 32-player server, HUD, scoreboard, voice) has no run behind it yet.
* The updater's IW4x self-update step only ran against a fake launcher script.
* The release workflow has never executed — no `v*` tag exists and nothing is pushed. Its steps mirror
  `build.yml`/`release.yml` and `check_kit.py` checks the trigger, but the first tag push is the first real test.
* The `Play …` launchers and the Steam Proton launch option were not exercised against a real install; the text
  is carried over from the v1.x kit, where players reported it working.
* The zip CI publishes contains the CI-built dll, the tag's raw kit contains the committed one. Both are
  self-consistent (each has its own `SHA256SUMS.txt`/`OURS_DLL`), and the updater is hash-driven, so a player
  who installs from the zip simply moves to the tag's dll on the next update — but it is a difference to know
  about before cutting `v2.0`.
* **Flipping `main/latest.json` to a v2.0 kit breaks the first update for installed v1.x players.** Their
  updater (the v1.x `iw4x32_update.py`, still running on their machine) swaps the kit files in and then copies
  `files/iw4x.exe` *and* `files/iw4x.dll` into the game folder unconditionally: with no `files/iw4x.exe` in the
  kit it dies with a `FileNotFoundError` **after** the kit was replaced, leaving a v2.0 kit next to a v1.x dll
  and exe. Two ways out, and both are a release-time decision, not a kit change:
  * a **bridge release** on `main` whose kit still carries `files/iw4x.exe` — the *official* r5154 exe — plus our
    dll: the old updater then installs official exe + our dll, which *is* the v2.0 state, and the kit it leaves
    behind is the v2.0 one, so the next update is clean;
  * or leave `main/latest.json` at v1.x and announce v2.0 as a download (the release zip), letting old players
    stay where they are.
  `check_kit.py` fails any kit that contains `files/iw4x.exe`, so a bridge kit has to be built outside the kit
  directory (or the check waived for it, deliberately).
