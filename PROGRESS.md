# PROGRESS — IW4x-32 (round 1: the engine component · round 2: the player kit + release workflow)

Task: `iw4x32/tasks/engine_component.md`, then `iw4x32/tasks/release_kit.md`. Branch `feat/iw4x32-kit`
(worktree of `feat/iw4x32-engine`). Never pushed.

## Status: both rounds done — the DLL builds clean and the 240 s smoke passes (round 1); the kit, its
## manifest, the release workflow and `check_kit.py` all exist and pass (round 2, below)

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
bash $HOME/Projects/IW4x-32/tools-re/build_iw4x_fork.sh . Release   # ~4 min, MSVC under Wine -> build/bin/Win32/Release/iw4x.dll
python3 iw4x32/tools/check_tables.py                                # ok - 14 arrays, 701 operands, 8 cvar domains, 6 size constants, 85 code patches, 14 hooks match engine_patches.json
python3 iw4x32/tools/smoke32.py                                     # stock exe + this build's DLL, 32 slots, 31 bots, 240 s
python3 iw4x32/tools/make_latest.py --dll build/bin/Win32/Release/iw4x.dll   # kit dll + OURS_DLL + SHA256SUMS.txt + latest.json
python3 iw4x32/tools/check_kit.py                                   # the kit, its hashes, no iw4x.exe install, the workflow
bash iw4x32/tools/sh_test.sh                                        # Linux installers against a fake game folder
bash iw4x32/tools/bat_test.sh                                       # Windows installers, under Wine cmd, real hashing
bash iw4x32/tools/upd_test.sh                                       # iw4x32_update.py against a fake game + local "GitHub"
git-privacy-check work                                              # clean
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
  prebuild commands (and there is no git inside the Wine prefix), so `iw4x32/tools/make_version_h.py` writes
  them before the Wine build — with the same nearest-`r*`-tag rule `premake5.lua` now uses (round 2).

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

---

# Round 2 — the player kit, `latest.json`, the release workflow, `check_kit.py`

Task: `iw4x32/tasks/release_kit.md`. The kit is adapted from the old one (`iw4x-32-public`, v1.x), with one
central change: **v2.0 installs one file, `files/iw4x.dll`. Nothing ever writes the game's `iw4x.exe`** — the
exe an older IW4x-32 replaced is put back from `backup/` instead.

## Deliverables

| file | what it is |
|---|---|
| `iw4x32/release/` | the kit: `Install IW4x-32.bat`, `Uninstall IW4x-32.bat`, three `Play …` launchers, `install-linux.sh`, `uninstall-linux.sh`, `play-linux.sh`, `iw4x32_update.py` / `.ps1` (auto-update), `README.txt`, `CHANGES.txt`, `AI_CREDITS.txt`, `SHA256SUMS.txt`, `files/iw4x.dll` (this branch's Release build, 3 847 680 bytes, sha256 `0d8a8f630df4…`) |
| `latest.json` (repo root) | `version` v2.0, `iw4x` r5154, the official r5154 exe/dll hashes, `base_url` = `https://raw.githubusercontent.com/shaunypnz/iw4x-32/v2.0/iw4x32/release/`, and the SHA-256 of all 15 kit files |
| `.github/workflows/iw4x32-release.yml` | on a `v*` tag: build Release on windows-2022 (same steps as `build.yml`), then `make_latest.py --dll <built>`, `check_kit.py`, zip the kit as `IW4x-32-<tag>.zip`, publish a draft GitHub Release with the zip + `iw4x.dll` + `SHA256SUMS.txt` |
| `iw4x32/tools/make_latest.py` | copies the built dll into the kit, syncs the `OURS_DLL` constant in the three installers that check it, writes `SHA256SUMS.txt` (CRLF) and `latest.json` |
| `iw4x32/tools/check_kit.py` | the nine checks: manifest shape, every kit file hashed and matching, no `files/iw4x.exe`, no installer writing `iw4x.exe` without `backup`, `OURS_DLL` = the kit dll, CRLF/LF endings, README/CHANGES version = manifest version, workflow triggers on `v*` and builds Release/Win32 |
| `iw4x32/tools/{sh_test,bat_test,upd_test}.sh`, `mini_certutil.c` | the tests below |

## Rules the kit holds to

* **One file.** Only `files/iw4x.dll` is copied into the game folder. Any line in an installer/updater that
  copies *to* the game's `iw4x.exe` must mention `backup` — that is the rule `check_kit.py` greps for, and it
  is what makes "no installer references replacing iw4x.exe" checkable rather than a promise.
* **Hashes are the contract.** Installers check the dll they are about to replace against the official r5154
  hash before touching anything; the updater re-hashes every download against `latest.json` and swaps nothing
  if one byte is off; after installing, the installer re-hashes the installed dll.
* **Bytes on the wire.** `.gitattributes` marks `iw4x32/release/**` as `-text`, so git stores the kit verbatim:
  `.bat`/`.ps1`/`.txt` keep CRLF, `.sh`/`.py` keep LF, and raw.githubusercontent serves exactly the bytes whose
  SHA-256 is in `latest.json`.
* **`OURS_DLL`** is a `PENDING` placeholder in the sources; `make_latest.py` fills it with the real dll hash, so
  the installers can never drift from the kit.

## What this round found

* **`REVISION_STR` was wrong for a fork.** premake's `getRevisionNumber()` returned `git rev-list --count HEAD`
  — 56 on this shallow worktree, 5163 on a full clone. IW4x's own `Updater.cpp` compares that string with the
  newest release tag, so *every player* would have seen "an update is available" forever. It now uses
  `git describe --tags --abbrev=0 --match r[0-9]*` → **r5154**, the release the DLL is built against. Upstream
  releases are unaffected (their tag *is* the commit count).
* **The Wine build cannot run premake's prebuild step** (no git inside the prefix) → `make_version_h.py`
  generates `src/version.h` / `version.hpp` with the same rule.
* **A real bug in `Install IW4x-32.bat`, found by running it under Wine cmd:** `goto :end` inside a `call`ed
  subroutine prints the message and then *returns to the caller*, so the "STOPPED: nothing was changed" path
  for a v1.x `iw4x.exe` without a backup went straight on to install `iw4x.dll` anyway. Subroutines now
  `exit /b 1` and the caller does `call :restore_v1_exe || goto :end`.
* **Wine's `certutil.exe` and `fc.exe` are stubs that print nothing** (and errorlevel 0 whatever they compare),
  so the `.bat` hash checks were untestable — `iw4x32/tools/mini_certutil.c` implements `certutil -hashfile …
  SHA256` with the same MSVC the project uses, and `bat_test.sh` drops it in the kit folder (cmd searches the
  current directory first). The installers then hash for real.
* **A stray `__pycache__/iw4x32_update.cpython-314.pyc` in the kit folder ended up in `latest.json`** — players
  would have downloaded a Python bytecode file. `make_latest.py` now skips build/editor junk, `check_kit.py`
  fails on any such file in the kit (verified: it reports it), and the workflow's zip step prunes `__pycache__`.

## Test log (round 2)

| run | setup | result |
|---|---|---|
| `.scratch/build3.log` | the bare CHECK command from a clean state (`src/version.h` deleted) | **ok** — `build_iw4x_fork.sh` now runs `make_version_h.py` itself, `REVISION_STR "r5154"`, `build/bin/Win32/Release/iw4x.dll` |
| `make_latest.py --dll …` | kit dll, `OURS_DLL`, hashes | ok — 16 files, `iw4x.dll 0d8a8f630df4…` matches the build |
| `check_kit.py` | the real kit | **ok** (and on a scratch tree it was shown to exit 1 for: a hash mismatch, an `iw4x.exe` copy without `backup`, a wrong workflow trigger, a stale `OURS_DLL`, a README version that disagrees, a broken CRLF) |
| `sh_test.sh` | `install-linux.sh` / `uninstall-linux.sh` vs a fake game folder | ok — official dll checked + backed up, ours installed, v1.x exe restored from `backup/`, modded dll refused, missing v1.x backup stops, no-game folder stops |
| `bat_test.sh` | the same cases for the `.bat` files, under Wine cmd with real hashing | ok — same five results, plus "already installed" on a re-run; this is where the `goto :end` bug showed up |
| `upd_test.sh` | `iw4x32_update.py` against a fake game folder and a local `latest.json` | ok — v2.0→v2.1 update installs only the dll and restores the v1.x exe; a second run changes nothing; when the IW4x launcher puts the official dll back it is repaired; a download that does not match `latest.json` installs nothing |
| `git-privacy-check work` | whole tree | clean |
| `.scratch/smoke_kitdll.log` | round 1's 240 s / 31-bot smoke, but with **the kit's dll** (the build3 one) | **ok — map up, 31 clients in `status`, no crash** (`IW4x-32/runs/20261013-011745-iw4x32-smoke`) |

## Not covered (round 2)

* **No real Windows client run.** The `.bat` files were run under Wine cmd with real hashing and stock cmd
  semantics, and the DLL was smoke-tested as a *server* module (round 1) — a player's Windows client starting
  the game through our dll is still untested.
* The updater's IW4x self-update path (`ensure_launcher`) only ever ran against a fake launcher script.
* The release workflow has never run: no `v*` tag exists and nothing is pushed. Its steps mirror `build.yml` /
  `release.yml`, and `check_kit.py` checks the trigger, but the first real run will be the first real test.
* The `Play …` launchers were not run against a real game (Steam/Proton launch options included are copied
  from the v1.x kit, which is the part players reported working).
* **Two builds of the same source do not produce the same bytes** (`/GL` + `/LTCG` bake a link time in: this
  branch built `01037f9c…` and then `0d8a8f63…`). So `make_latest.py --dll` has to be run against the exact dll
  that goes into the kit, which is what the workflow does — and the kit's hashes are only ever as reproducible
  as the build that fed them.
* **Moving installed v1.x players to v2.0 is a release decision that is not made here**: their updater copies
  `files/iw4x.exe` unconditionally, so a v2.0 kit (no such file) leaves them mid-migration. The options — a
  bridge kit carrying the *official* exe, or leaving `main/latest.json` at v1.x and announcing v2.0 as a
  download — are written out in `QWEN_REPORT.md` §7.


PROGRESS: 5% - done: baseline read of IW4x32.cpp + test script, report skeleton / next: reproduce map-change failure with client console captured

PROGRESS: 10% - done: 8-bot run (client came back, slot 8 - bug needs slot >=18), found client console path / next: reproduce with 28 bots + client in slot 28
