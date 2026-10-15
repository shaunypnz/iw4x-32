# Round 1 (2026-10-15) - sync the IW4x-32 fork with upstream r5167

Branch `feat/sync-upstream-r5167`, fork head `dedab8d5`, upstream release tag `r5167` = `dc315210`.
Merge base: `d1b175da Add server-side demo recording` - the fork is 10 upstream commits behind.

## CHECK commands (from the worktree root)

```
git merge-base --is-ancestor r5167 HEAD
bash $HOME/Projects/IW4x-32/tools-re/build_iw4x_fork.sh . Release
python3 tools/aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll --bots 27 --client --minutes 5 --map-change-at 2
```

```
1. git merge-base --is-ancestor r5167 HEAD                     PASS (merge commit b5d7f58b)
2. build_iw4x_fork.sh . Release                                PASS - build/bin/Win32/Release/iw4x.dll,
                                                                   md5 6fe7fc0c2f97a7a77c37f64002efec4e, REVISION 5167
3. tools/aiboi_test.py --bots 27 --client --minutes 5 --map-change-at 2   PASS (13/13 checks, run 1, first try)
```

The build log has no errors and no new warnings from the merged-in files (`Discord.cpp`, `Companion.cpp`,
`Proxy.cpp`, `Steam.cpp` all compiled). `iw4x32/tools/make_version_h.py` now resolves `r5167` from the merged tag,
so the DLL reports REVISION 5167 - the fork ships upstream's revision number, which is what `Updater.cpp`
compares against `latest.json`.

## What upstream changed (the 10 commits)

| commit | subject | files |
|---|---|---|
| 9f9667ae | Add companion dependency | `.gitmodules`, `deps/companion` (new submodule), `deps/premake/companion.lua` |
| 1af6904e | Remove Steam mod presence | `Friends.cpp`, `DllMain.cpp`, `Steam/Proxy.cpp/hpp`, `Steam/Steam.cpp` (-90) |
| c71d70f1 | Add Steam companion registration | new `Steam/Companion.cpp/hpp` (+653), `Steam/Steam.cpp/hpp` |
| 731d2607 | **Fix command injection through Discord join secrets** | `Discord.cpp` |
| dd509ffa | Change Discord rich presence to describe the match with map art | `Discord.cpp/hpp` (+458) |
| 661fb8b7 | Fix Discord rich presence text in non-Western languages | `Discord.cpp` |
| b8baff4a | Fix Discord rich presence text with DEL and C1 control characters | `Discord.cpp` |
| 61ab31ae | Change Steam companion to companion64 and companion launcher | `deps/companion`, `Steam/Companion.cpp/hpp` |
| e074ef0a | Fix Discord rich presence in private match lobby | `Discord.cpp` |
| dc315210 | Fix stale relay reference in Discord control character comment | `Discord.cpp` |

## Conflicts and how they were resolved

**There were none.** `git merge r5167` merged clean with the `ort` strategy:

```
Merge made by the 'ort' strategy.
 13 files changed, 1245 insertions(+), 172 deletions(-)
```

The reason is that the two sides touch disjoint files. Everything the fork changes
(`git diff --name-only d1b175da..dedab8d5`: `iw4x32/**`, `src/Components/Modules/IW4x32*.{cpp,hpp}`,
`IW4x32Tables.hpp`, `Loader.cpp`, `Dedicated.*`, `ServerList.cpp`, `Updater.cpp`, `Voice.cpp`, `Vote.cpp`,
`src/Game/Functions.*`, `src/Game/Server.cpp`, `premake5.lua`, `tools/aiboi_test.py`, `latest.json`, release kit,
CI) is outside the 13 files upstream touched (`Discord.*`, `Friends.cpp`, `DllMain.cpp`, `Steam/*`, `.gitmodules`,
`deps/companion`, `deps/premake/companion.lua`).

Verified the merge lost nothing fork-side and added nothing else:

```
git diff --stat dedab8d5..HEAD   ->  exactly the 13 upstream files, +1245/-172
```

The one thing the merge did need beyond the merge itself: the new `deps/companion` submodule was not cloned in
this worktree. `build_iw4x_fork.sh` only inits submodules when `deps/zlib/zlib.h` is missing, and it seeds them
from the main checkout's local clones (offline), which do not contain `companion` yet. Fetched it once:

```
git submodule update --init deps/companion     # -> 46d9b47e (heads/main), libcompanion headers only
```

`deps/premake/companion.lua` only adds `deps/companion/libcompanion` to `includedirs` (header-only,
`<libcompanion/protocol.hxx>`), and `dependencies.load()` in `premake5.lua` requires every `deps/premake/*.lua`,
so no project file needed editing.

## New 18-slot sites in upstream's code, and what was done for 32

Read every line the merge brought in (`Discord.cpp` 603 lines, `Companion.cpp` 593, `Proxy.cpp`, `Steam.cpp`,
`Friends.cpp`, `DllMain.cpp`). **No new 18-wide array, no new `< 18` check, no new `Game::MAX_CLIENTS` loop.**
What the new code does with player counts, site by site:

| site | what it does | 32-player verdict |
|---|---|---|
| `Discord.cpp` `Observe()`: `scene.players = Game::cgArray[0].snap ? ...->numClients : 1` | player count for the presence | `numClients` sits in `snapshot_s` before `clients[18]`; the fork's engine patch list (`engine_patches.json` -> `arrays`) does not grow the snapshot struct, so the field reads correctly and simply reports up to 32 |
| `Discord.cpp` `Build()`: `r.partySize = std::clamp(scene.players, 1, 64)` | Discord party size | clamps at 64, so 32 players pass through unchanged - no edit needed |
| `Discord.cpp` `Build()`: `r.partyMax = scene.capacity > 0 ? std::clamp(scene.capacity, r.partySize, 64) : 0` with `scene.capacity = Party::GetMaxClients()` | Discord party max | `Party::GetMaxClients()` parses the `sv_maxclients` server-info value, so a 32-slot server publishes `partyMax = 32` (upper clamp 64) - correct as is |
| `Discord.cpp` `Observe()`: `scene.server = Party::GetHostName()` | server name | reads the server-info container, no slot involvement |
| `Friends.cpp` `IsClientInParty()`: `clientNum >= ARRAYSIZE(Dedicated::PlayerGuids)` | party/friend check per slot | `ARRAYSIZE` follows the fork's `PlayerGuids[Game::MAX_CLIENTS][2]`, so it already covers 32 slots (this is the site the fork fixed earlier; upstream's edit removed the neighbouring mod-ID block, not this line) |
| `Steam/Companion.cpp` (whole file) | Steam companion record: file mapping / `/dev/shm` file, `rundll32` attach | no player data at all |
| `Steam/Proxy.cpp` `SelectOwnedGame()` (replaces `SetMod`/`RunMod`) | picks the app id the account owns | no player data |
| `Steam/Steam.cpp` `Companion::Register/AppId` | registers the title | no player data |
| `DllMain.cpp` (removed `Steam::Proxy::RunMod()`) | the old mod re-exec parent wait | gone upstream, nothing fork-side referenced it (`grep -rn "Proxy::RunMod\|Proxy::SetMod" src/` is empty; `ModList::RunMod` is a different function) |

The security fix (`JoinGame`) parses the Discord join secret with `Network::Address` and only accepts a
non-local `NA_IP` before calling `Party::Connect` - it never hands the secret to the console. Nothing
32-specific there either.

So: **zero IW4x-32 edits were needed on top of the merge.** I re-checked that claim with a grep over the merged
files for the patterns the task names (`MAX_CLIENTS`, `\[18\]`, `< 18`, `clientNum`, `playerNames`,
`playerClientNums`, `svs_`) - the only hits are the `Friends.cpp` `ARRAYSIZE` line above.

## Build and live test results

Build (CHECK 2): clean, no errors, `Discord.cpp` / `Companion.cpp` / `Proxy.cpp` / `Steam.cpp` / `IW4x32.cpp` all
compiled and linked; `build/bin/Win32/Release/iw4x.dll` = 3,864,064 bytes, md5 `6fe7fc0c2f97a7a77c37f64002efec4e`.

Live test (CHECK 3), the exact command from the task, on the test box, first run after the merge:

```
python3 tools/aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll --bots 27 --client --minutes 5 --map-change-at 2
[aiboi_test] ok   server_alive: every status poll answered
[aiboi_test] ok   no_new_crash_dumps: 0 new minidump(s)
[aiboi_test] ok   players_in: most 28 of 28 wanted
[aiboi_test] ok   client_slot_32: highest human slot 27, needs >= 18
[aiboi_test] ok   client_in_before: live-test in status before the change
[aiboi_test] ok   map_changed: maps in status: mp_rust -> mp_crash
[aiboi_test] ok   session_restarted: bot guids before ['bot0','bot1']..27 vs after ['bot27','bot28']..27
[aiboi_test] ok   client_rejoined: live-test in status again after the change: True
[aiboi_test] ok   rejoin_within: back after 72 s, limit 150 s
[aiboi_test] ok   rejoin_slot_32: slot 27 after the change, needs >= 18
[aiboi_test] ok   client_process_up: client process still up at the end
[aiboi_test] ok   client_follow_line: 1 'Server changing map mp_crash' line(s) in userraw/console_mp.log*
[aiboi_test] ok   players_back_after: most 28 of 28 after the change
[aiboi_test] PASS {'players_max': 28, 'players_wanted': 28, 'client_slot': 27, 'maps_seen': ['mp_crash', 'mp_rust'],
                   'polls': 9, 'client_follow_lines': 1, 'iw4x32_marker_lines': 1, 'new_crash_dumps': 0}
```

The server console carried `IW4x32: patched the stock iw4x.exe (md5 9c42ffa4...) - 14 arrays, 701 operands,
85 code patches (27 layout sites), 14 hooks - 32 players en...` - the 32-player engine patch still applies to the
stock exe with the merged DLL, and `iw4x32_marker_lines: 1` is the harness seeing that line. The client console
shows both map-change notices (`Server changing map mp_rust` then `mp_crash`) and the client came back in slot 27.

The `Adding channel: error` lines in the server console tail are the stock voice-channel setup under Wine on the
test box, present before this merge too - not a new failure.

Offline harness self-check (`python3 tools/aiboi_test.py --self-test`, the probe-sees-a-bad-case proof):
`ok - 11 checks: good transcript passes, 0 wrong`.

## Notes for the next round (harness, not code)

- `build_iw4x_fork.sh` on a fresh worktree inits every submodule from the main checkout's local clones. If a
  previous attempt was interrupted, `git submodule update --init -q` can exit 1 printing nothing (the `-q` hides
  the leftover-lock error) and the build script then dies with no log. Running the same command without `-q`
  shows the real work and succeeds; after that the build script skips the step (`deps/zlib/zlib.h` exists).
- Backgrounding the build from this harness (`nohup`/`setsid`) does not survive the tool call - the log stays
  empty and nothing is left running. Run the build and the live test in the foreground with a long timeout.

## Open questions / release-time follow-ups (not CHECK failures)

1. `iw4x32/tools/make_latest.py` still defaults to `--iw4x r5154` and `latest.json` at the repo root still says
   `"iw4x": "r5154"`. That file is generated when a kit is cut (it hashes `iw4x32/release/files/iw4x.dll`), so it
   is deliberately untouched here - but the next kit must be made with `--iw4x r5167`, and
   `iw4x32/release/files/iw4x.dll` + `SHA256SUMS.txt` regenerated, or installed players keep the pre-sync DLL.
   `Updater.cpp` compares `REVISION_STR` (now `r5167`) against the upstream release tag, so the in-game
   "update available" flag is correct already.
2. Discord rich presence and Steam companion registration are client-side and cannot be judged by the live test
   (the test box has no Discord client and the LAN run does not go through Steam). They compile, and the client
   ran the whole session with them in and produced no crash dump; a human with Discord should eyeball the
   presence on a 32-slot server (`partySize`/`partyMax` should read e.g. 28/32).
3. Upstream's `snapshot_s` still holds `clients[18]` and the fork does not grow it (`engine_patches.json` has no
   snapshot array). The Discord presence only reads `numClients`, which sits before that array, so this merge is
   unaffected - but it is the same 18-wide session/match-data layer the prior task logged as an open issue at
   match end (`SetClientMatchData("players", "18".."28")` errors). Still open, still not this task.

NEXT ROUND: no - all three CHECKs pass on the merge commit: `r5167` is an ancestor of HEAD, the fork builds clean
(r5167 DLL), and the live 27-bot + client + map-change test passes 13/13 with the client in slot 27 and 0 crash
dumps. Nothing in the merged code needed a 32-player edit, so there is no follow-up work that would change a
CHECK result. What is left is release-time work (regenerate the kit and `latest.json` with `--iw4x r5167`) and a
human eyeball on Discord rich presence.

The report of the previous task on this branch (map-change rejoin, rounds 1-6) is archived at
`runs/QWEN_REPORT-mapchange-rejoin-archived.md`.
