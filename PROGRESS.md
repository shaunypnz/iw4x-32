# PROGRESS — IW4x-32 engine component (stock iw4x.exe + our iw4x.dll = 32 players)

Task: `iw4x32/tasks/engine_component.md`. Branch `feat/iw4x32-engine`. Never pushed.

## Status: done — all 5 deliverables exist, the DLL builds clean, the 240 s smoke test passes

| # | Deliverable | State |
|---|---|---|
| 1 | `iw4x32/tools/gen_tables.py` → `src/Components/Modules/IW4x32Tables.hpp` | done, header committed (956 lines) |
| 2 | `src/Components/Modules/IW4x32.cpp/.hpp` (component: arrays, operands, size constants, cvar domains, code patches + dual switch, hooks, engine32c port) | done, compiles clean |
| 3 | the 9 `dll_patches.json` engine pointers | done (see below) |
| 4 | `iw4x32/tools/check_tables.py` | done, passes; proven sensitive (wrong addr / missing row / wrong byte / count → exit 1) |
| 5 | `iw4x32/tools/smoke32.py` | done; first full run found a crash, root-caused and fixed, re-running |

## Commands

```
bash $HOME/Projects/IW4x-32/tools-re/build_iw4x_fork.sh . Release   # ~4 min, MSVC under Wine
python3 iw4x32/tools/check_tables.py                                # ok - 14 arrays, 701 operands, 8 cvar domains, 6 size constants, 85 code patches, 14 hooks match engine_patches.json
python3 iw4x32/tools/smoke32.py                                     # stock exe + this build's DLL, 32 slots, 31 bots, 240 s
```

## How it works (short)

* Component registers right after `Logger` in `Loader::Initialize()`, i.e. before any engine game code runs.
* `VerifyEngine()` checks the exe MD5 (`9c42ffa4f7aefd08fd501b40f5e41eab`) and every byte the tables expect;
  nothing is written unless all of it matches. `iw4x32-disable` next to `iw4x.exe` skips patching entirely.
* 14 enlarged arrays come from one `VirtualAlloc`; the 701 operands store `new_array_offset`, resolved at
  runtime to `alloc_base + offset` (the `cg_tail` ones are `old + 0x4868`), so the layout is not baked in.
* 85 code patches (27 of them `dual`) + 6 size constants + 8 cvar-domain byte patches.
* 14 hooks: `Utils::Hook(va, stub, HOOK_JUMP).install()->quick()`; the stubs are `__declspec(naked)` and hand
  control back with `jmp dword ptr [s_back_...]` (indirect through a memory cell: no register, no flag touched).
* Dual layout: `SV_SpawnServer` hook registers the `iw4x32` / `sv_iw4x32` dvars and picks 32- or 18-player
  bytes for the 27 dual sites; `SV_DirectConnect` refuses clients without the `iw4x32` marker;
  `CG_ParseServerinfo` reads the server's `sv_iw4x32` and switches the same 27 sites for a connecting client.
* Lag compensation (`engine32c/antilag.c`) is ported as two cdecl C functions that replace
  `G_AntiLagRewindClientPos` (0x4C1120) and `G_AntiLagRestoreClientPos` (0x440040) with 32-entry buffers
  in a single global store (the engine's 0x1C4 caller-stack store would overflow at 32).

## The 9 DLL engine pointers

| manifest site | source | fix |
|---|---|---|
| `Game::svs_clients` | `src/Game/Server.cpp:33` | volatile seed (`s_svs_clients_stock`), re-pointed at the new array |
| `Game::level_bgs` (TLS + .rdata table) | `src/Game/Functions.cpp:396` | volatile seed, re-pointed |
| `Game::cgMedia` (`post_cg_globals` ×2) | `src/Game/Functions.cpp:392` | volatile seed, re-pointed |
| `cg_tail cmp eax,&cg.clientinfo[18]` | `src/Components/Modules/CardTitles.cpp:12` | nothing to do: the bound comes from `Game::MAX_CLIENTS` (32) |
| `ui_playerClientNums` | `src/Components/Modules/Voice.cpp:403` | `IW4x32::PlayerClientNums()` |
| `ui_playerNames` ×2 | `src/Components/Modules/Vote.cpp:410,418` | `IW4x32::PlayerNames()` |

Verified in the built DLL: zero folded `0x31D9390` / `0x19BD680` / `0x8EE4B8` / `0x8ED4C8` immediates left in
`.text` (LTCG would have baked them in otherwise — that is what the volatile seeds prevent); the only
`0x62E4BD4`/`0x62E5054` immediates left are the not-patched fallbacks of the two accessors.

## Findings / gotchas (for the next person)

* **LTCG folds pointer globals.** `Game::svs_clients = (client_s*)0x31D9390` gets constant-propagated into
  code (`push [0x8EE4B8]` style). The volatile-seed trick is required, and the built DLL must be scanned for
  leftover immediates after every change.
* **`Utils::Hook(...).install()->quick()`** — `quick()` clears the static `Hook::installed` flag so the
  temporary's destructor does not restore the original bytes. Without `quick()` the hook is undone at once.
* **`engine32c/stubs.S` addresses are stale** for some hooks; the authoritative hook VAs and `replaced`
  bytes are in `engine_patches.json` (all 14 were checked against the pristine exe with capstone).
* **A stub must not touch any register or flag the resumed engine code still needs.** The first 32-player
  run crashed at `0x487C25` (`Session_GetXuidForSlot`): the stub used the codebase's `mov eax, ADDR; jmp eax`
  idiom to get back, which overwrote `eax` = the slot the resumed code was about to index with
  (`lea ecx,[eax+0xA] … cmp [edx+esi*8],0`). All stubs now hand control back with
  `jmp dword ptr [s_back_…]`, an indirect jump through a `.data` cell: no register, no flag, no ±2 GB range
  question. `SscmSet`/`SscmTest` resume on a `je` whose flags come from an earlier engine `cmp`, so they have
  to leave the flags alone as well.
* `version.h` / `version.hpp` are gitignored and generated by premake's `setversion`; the build script strips
  prebuild commands, so they are copied in from the main checkout.

## Test log

| run | setup | result |
|---|---|---|
| `20261012-230655-iw4x32-quick` | stock exe + this DLL, 32 slots, 31 bots, 90 s | map up, 31 clients in `status`, no crash — first green run |
| `20261012-231001-iw4x32-full` | same, 240 s | crashed 60-87 s in, empty minidump |
| `20261012-232449-iw4x32-crash1` | same, plus the first-chance reporter | `exception C0000005 at 00487C25` — the `eax` clobber above |
| `20261012-233922-iw4x32-fix1` | fixed stubs, 240 s | **ok — map up, 31 clients in `status`, no crash** |
| `20261012-235445-iw4x32-final` | comment-only changes since fix1, 240 s | **ok** |
| `20261013-000959-iw4x32-off` | `iw4x32-disable` next to `iw4x.exe`, 18 slots, 17 bots, 60 s | `IW4x32: iw4x32-disable found - not patching`, map up, no crash — the escape hatch works |
| `20261013-001113-iw4x32-final2` | final source (`StubFor` names verified in `VerifyEngine`), 240 s | **ok** |

`check_tables.py` was also shown to be sensitive: a wrong address, a dropped operand row, a wrong byte string
or a wrong count each makes it exit 1.
