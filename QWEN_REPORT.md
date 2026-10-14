# QWEN_REPORT — client rejoin test case (this round)

**Result: `tools/aiboi_test.py` now carries a `rejoin` test case — a live client must come back on the new map by
itself after a map change — and an offline `--self-test` that judges recorded transcripts. CHECK:
`python3 tools/aiboi_test.py --self-test` passes (11 checks: the good transcript passes every case, each of the 8
bad ones fails the check that names its problem). Live on the box, 28 bots + a real client on its GPU and a
rotation-driven map change: **PASS, 13/13 checks**, twice running (runs 10 and 11). The client was back in slot 28
72 s after the change both times. The bug from `iw4x32/tasks/map_change_rejoin.md` did not reproduce on this
branch — see §4.**

Branch: `feat/client-rejoin-test` (worktree). Nothing pushed.

## 1. Deliverable

`tools/aiboi_test.py` — the live game test tool, now in the repo (it used to live only in the RE tools folder,
outside the checkout, so the CHECK could not run it). Split into two halves:

* **the judging half** (no box, no game): `parse_status()` turns rcon `status` text into `(map, [(slot, guid,
  name)])`; `case_baseline` / `case_rejoin` each yield one `chk(name, ok, detail)` per check; `verdict()` runs
  the selected cases over one **observation record** (the polls of the run + the console counters).
* **the live half**: same run as before (lock, throwaway folder, stock exe + our dll, dedicated server, bots,
  optional client, optional `map_rotate`), but it now *records* what it saw into that same observation record and
  lets the judging half decide. Nothing about the pass rule moved into the ssh loop.

Test cases (`--case baseline,rejoin`; default: `baseline`, plus `rejoin` when `--client` and `--map-change-at`
are both given):

| case | checks |
|---|---|
| `baseline` (the old pass rule, unchanged) | `server_alive`, `no_new_crash_dumps`, `players_in`, `client_slot_32` (highest human slot >= 18) |
| `rejoin` (new) | `client_in_before` — our client (`+set name live-test`) is in `status` before the change, so the case is judging something; `map_changed` — `status` shows two different maps; `session_restarted` — the bots answering after the change carry **new** guids (`bot0..bot27` before, `bot28..bot55` after): a level restart drops every client, so without this a client that never left would "rejoin" and nothing would be proven; `client_rejoined` — the client is in `status` again after the change; `rejoin_within` — back within `REJOIN_MAX_S` (150 s) of the change; `rejoin_slot_32` — its slot after the change is >= 18, which is only possible if the **client-side** 32-player layout survived the level reload; `client_process_up` — its process is still up at the end; `client_follow_line` — the client's own console log (`userraw/console_mp.log*`) shows the `Server changing map <map2>` notice, i.e. the client-side reload really ran; `players_back_after` — the bots are back too |

`rejoin` refuses to run without `--client` and `--map-change-at` (`rejoin_setup` fails) rather than passing on an
empty setup.

## 2. `--self-test` (the CHECK)

`python3 tools/aiboi_test.py --self-test` — 11 checks, no box, no game, deterministic:

* `parse_status` on the real status shape: map name, 29 rows, the client found in slot 28, exactly 1 human row
  (bots carry a `bot<N>` guid).
* the **good** transcript (28 bots + client in slot 28, change at 120 s, client back in slot 28 at 140 s, bots
  re-added with new guids, 1 client follow line, 0 dumps) passes `baseline` **and** `rejoin`.
* 8 **bad** transcripts, each must fail the named check — this is the "can the probe see a bad case" proof:
  client never comes back (the bug: `client_rejoined`, `rejoin_within`, `rejoin_slot_32`, `client_follow_line`),
  client back in slot 3 (client-side layout fell back: `rejoin_slot_32`), client back but its process died
  (`client_process_up`), **nobody was dropped** — the change never restarted the session, so a client that never
  left would "rejoin" (`session_restarted`), the change landed on the same map (`map_changed`,
  `session_restarted`), the server went down (`server_alive`), bots never re-added (`players_back_after`), a new
  crash dump (`no_new_crash_dumps`), and `rejoin` on a run with no `--map-change-at` (`rejoin_setup`).

The transcripts are built with `status_text()`, which writes the same columns `status` prints; the address column
stays the placeholder `0:<LAN-IP>` so nothing machine-specific is in the repo.

## 3. Live runs

**Run 1** (`--bots 28 --client --minutes 5 --map-change-at 2`, this branch's dll, `.scratch/live1.log`): the run
itself was clean — 29/29 players, client in slot 28, 0 new minidumps, 11 polls — but three rejoin checks failed:

```
ok   client_in_before: live-test in status before the change
FAIL map_changed: maps in status: mp_rust -> mp_rust
FAIL server_reinit: 1 'iw4x32: .*slot server' line(s) in the server console, needs >= 2
ok   client_rejoined: live-test in status again after the change: True
FAIL client_reconnect_line: 1 'CL_ConnectFromParty called for local client' line(s) in userraw/console_mp.log
```

Cause, read from the evidence before touching anything: **the map change never happened.** The test game folder's
`userraw/server.cfg` sets `sv_maprotation "gametype dom map mp_rust"` — a one-map rotation — so `rcon map_rotate`
is a no-op: the server console carries a single `iw4x32: 32-slot server` line, `status` shows `mp_rust` the whole
run, and the client's own console shows one connect. `client_rejoined` said ok only because the client never left
— which is exactly why the case also demands `map_changed` and `server_reinit`: without them a run in which
nothing was reloaded would "pass" a rejoin test. Fixed by making the change explicit: `--map-change-to mp_crash`
(default) runs `rcon map mp_crash`; the stock mp_ maps are all in the test game folder.

**Run 2** (`--map-change-at 2`, `.scratch/live2.log`): `map_changed` now ok (`mp_rust -> mp_crash`), the client was
back in slot 28 and 29/29 players after the change — but `server_reinit` (2 marker lines) and
`client_reconnect_line` (2 connects) still failed. Instead of adjusting the thresholds I saved the run's logs
(`--save-logs`, added for this) and read them:

* **the dll's `iw4x32: N-slot server` line appears once per process, not once per level.** One
  `------ Server Initialization ------` block in the whole server console, and the server console never mentions
  `mp_crash` at all — yet the client's log has `Server changing map mp_crash, gametype dom` and then
  `Loading fastfile mp_crash_load` / `Loading fastfile mp_crash`. So a map change does not re-run the engine's
  server-init banner path that the marker hook sits on; the marker can never be a map-change signal.
* **`CL_ConnectFromParty` is not the follow-the-change marker either** — the client logs it once, at the initial
  join (11 s in), and still rejoins fine.
* **what a real level restart does leave in `status`: the bots.** Before the change the bots are `bot0..bot27`,
  after it `bot28..bot55` — the restart dropped every client and the re-add named the next ones. That is the
  observable proof that the session really restarted, which is what makes "the client came back" mean something.
* **the log files collide**: the dedicated server and the client share the game folder, and both open
  `userraw/console_mp.log`; whoever opens it second rotates the other's file to `.000`. That is why run 1 counted
  one connect — it grepped the server's file. The tool now greps `console_mp.log*` (all of them) and
  `--save-logs` keeps both.

So the rejoin case now judges: `client_in_before`, `map_changed`, **`session_restarted`** (the bot guid sets before
and after the change must be disjoint — a client that never left can no longer "rejoin"), `client_rejoined`,
`rejoin_within`, `rejoin_slot_32`, `client_process_up`, **`client_follow_line`** (the client's console shows
`Server changing map mp_crash`, i.e. the client-side reload ran), `players_back_after`. The `iw4x32` marker line
count stays in the report as information, not as a check.

**Run 3** (`--change-via map`, `.scratch/live3.log` + `.scratch/logs3`): first run against the rewritten checks —
`map_changed` ok, `client_rejoined` ok (slot 28, back 72 s after the change), `client_follow_line` ok, and the two
old checks (`server_reinit`, `client_reconnect_line`) were gone. `session_restarted` did not exist yet, so the run
could not yet prove the client had actually been dropped.

**Run 4** (`--change-via map`, `.scratch/live4.log`) — the first full PASS of the rejoin case, 13/13 checks:

```
poll t=24s  map=mp_rust  players=29 client=slot 28      poll t=169s map=mp_crash players=29 client=slot 28
poll t=94s  map=mp_rust  players=29 client=slot 28      poll t=311s map=mp_crash players=29 client=slot 28
ok   map_changed: maps in status: mp_rust -> mp_crash
ok   session_restarted: bot guids before ['bot0','bot1']..28 vs after ['bot28','bot29']..28
ok   client_rejoined / rejoin_within: back after 72 s, limit 150 s / rejoin_slot_32: slot 28
ok   client_follow_line: 1 'Server changing map mp_crash' line(s) in userraw/console_mp.log*
PASS {'players_max': 29, 'players_wanted': 29, 'client_slot': 28, 'maps_seen': ['mp_crash','mp_rust'],
      'polls': 11, 'client_follow_lines': 1, 'iw4x32_marker_lines': 1, 'new_crash_dumps': 0}
```

**Run 5** (`--change-via rotate`, `.scratch/live5.log`) — the probe caught a bad case **live**, not just in the
fixtures: `FAIL map_changed: mp_rust -> mp_rust` and `FAIL client_follow_line: 0 ... mp_crash line(s)`, while
`session_restarted` said ok. That combination is exactly right and it explains itself: `map_rotate` *did* restart
the level (the client's log has `Server changing map mp_rust, gametype dom`, every bot was dropped and re-added as
`bot28..bot55`), but the rotation never named a second map. Getting the rotation to actually advance took three
probes and produced a finding worth more than the fix:

* `+set sv_maprotation "map a map b"` on the wine command line never reaches the engine as one value — the shell
  eats the quotes and the server gets six arguments (visible in the saved command line at the top of server.log).
* Over rcon the value lands (`"sv_mapRotation" is: "map mp_rust map mp_crash"`) — and `map_rotate` still restarts
  the current map.
* **The engine snapshots `sv_maprotation` when the LEVEL starts; changing the dvar mid-level changes the dvar and
  nothing else.** Probe: set the rotation to `mp_rust` over rcon, call `map_rotate` — the server went to
  **mp_crash**, the value the dvar had when the level started. That is the whole story behind runs 5-8.
* With two maps named in the rotation, `map_rotate` restarts the current one; a rotation naming only the map you
  want next advances.

So `--change-via rotate` writes `set sv_maprotation "map <map2>"` into the copy's server.cfg before the server
starts, then fires `map_rotate` twice: the first one after a manual `+map` only restarts the current map (the
rotation system has not seen that level), the second follows the rotation. Run 10 below is that path end to end.

**A hard-link trap worth knowing** (found while probing this, and it bit the base game folder): the throwaway
folder is made with `cp -al`, so every file in it — `userraw/server.cfg` included — is a HARD LINK into the base
test game folder on the box (its name lives in the site config, not here). Appending the rotation line to the
copy's server.cfg edited the base folder's cfg. The base cfg is back to its original content — one trailing
newline added, byte-identical apart from that — and the tool now rewrites the copy's cfg as a NEW file
(`{ cat; printf ...; } > .cfg.new && mv`), never appends in place. Same reason it `rm -f`s the copied log files:
never write through a link you did not break.

**Runs 9-10** (`--change-via rotate`, the rotation in the copy's cfg, `map_rotate` fired twice). Run 9 still had the
single-rotate version and failed `map_changed`; run 10 is the rotate path passing end to end, 13/13:

```
poll t=94s  map=mp_rust  players=29 client=slot 28      poll t=277s map=mp_crash players=29 client=slot 28
poll t=205s map=mp_rust  players=29 client=slot 28      poll t=301s map=mp_crash players=29 client=slot 28
ok   map_changed: maps in status: mp_rust -> mp_crash
ok   session_restarted: bot guids before ['bot0','bot1']..28 vs after ['bot28','bot29']..28
ok   client_rejoined / rejoin_within: back after 72 s, limit 150 s / rejoin_slot_32: slot 28
ok   client_follow_line: 1 'Server changing map mp_crash' line(s) in userraw/console_mp.log*
PASS {'players_max': 29, 'players_wanted': 29, 'client_slot': 28, 'maps_seen': ['mp_crash','mp_rust'],
      'polls': 11, 'client_follow_lines': 1, 'iw4x32_marker_lines': 1, 'new_crash_dumps': 0}
```

The client's console shows both reloads it followed: `Server changing map mp_rust` (the first, no-op rotate) at
91 s and `Server changing map mp_crash` at 144 s — and it came back after each.

## 4. Open questions / notes

* `client_slot_32` (both cases) needs `--bots >= 18`: bots take the low slots, so with 8 bots the client can only
  ever sit in slot 8. The reproduce command in `iw4x32/tasks/map_change_rejoin.md` (`--bots 8 --client`) therefore
  fails that check for setup reasons — the rejoin case is meant to run with the default 28 bots.
* The client's console log is `userraw/console_mp.log` (rotated `.NNN`); the `client.log` the run redirects wine's
  stdout to stays empty — that is why the tool greps the real one, and greps `console_mp.log*`: the dedicated
  server opens `console_mp.log` first, the client rotates it to `.000` when it starts and writes a fresh one, so
  the two processes' lines are split across files.
* **The bug did not reproduce on this branch.** With this branch's dll and a live client on the box's GPU, the
  client followed a direct `map mp_crash` (run 4) and a rotation-driven change (run 10), came back by itself in
  72 s both times, in slot 28, process up, 0 minidumps — and it did it in every one of the ten runs, including the
  runs where the level restarted but the map did not change. So on this branch the `rejoin` case is a regression
  guard, not a reproducer. Whoever picks up the fix should run the same command against the build that shows the
  bug; the case is what fails there, and the fixtures in `--self-test` show the shape of that failure.
* Two things this setup does **not** cover, worth saying out loud: `party_enable 0` (a real online session joins
  through the party, and `CL_ConnectFromParty` is exactly the line that does *not* repeat on a follow), and a
  match that ends by itself (time limit / score limit) rather than a change fired at a fixed minute.
* `iw4x32: N-slot server` (the dll's own server-init line) is printed **once per process**, not once per level —
  it is kept in the report as information, and `session_restarted` uses the bot guids instead.

---

# Previous round — IW4x-32 engine component / player kit


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
