# QWEN_REPORT — IW4x-32 engine component

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
