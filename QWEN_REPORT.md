# Round 1 (2026-10-16) - sync the IW4x-32 fork with upstream r5168

Branch `feat/sync-upstream-r5168`, fork head before the merge `808f9340` (the r5167 sync), upstream release tag
`r5168` = `80eaa34b`. Merge base: `dc315210 Fix stale relay reference in Discord control character comment` -
the fork was exactly 1 upstream commit behind.

Merge commit: `a4b1b214 Merge tag 'r5168' into feat/sync-upstream-r5168`.

## CHECK commands (from the worktree root) and results

```
1. git merge-base --is-ancestor r5168 HEAD                                   PASS (merge commit a4b1b214)
2. bash <tools-re>/build_iw4x_fork.sh . Release                              PASS - build/bin/Win32/Release/iw4x.dll,
                                                                                  3864064 bytes, md5 a8d6bcda5374611bc23177113070add2,
                                                                                  src/version.h: REVISION 5168 / REVISION_STR "r5168",
                                                                                  no compile errors (only the usual 125 x D9025
                                                                                  /Zi->/Z7 override warnings from the msvc-wine shim)
3. python3 tools/aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll \
       --bots 27 --client --minutes 5 --map-change-at 2                      PASS 13/13, twice, identical numbers
                                                                                  (see "Live test" below)
```

## What upstream changed (the 1 commit)

`80eaa34b Fix crash saving server cache with non-UTF-8 server names` - one file, 6 added / 1 removed line, in
`src/Components/Modules/ServerList.cpp`:

```cpp
-    Utils::IO::WriteFile (ServerCacheFile, root.dump ());
+    // Server-supplied strings are not necessarily valid UTF-8 (e.g., hostnames
+    // in a legacy code page), so replace invalid bytes instead of throwing.
+    //
+    Utils::IO::WriteFile (ServerCacheFile,
+                          root.dump (-1, ' ', false,
+                                     nlohmann::json::error_handler_t::replace));
```

`nlohmann::json::dump ()` defaults to `error_handler_t::strict`, which throws
`type_error.316` on invalid UTF-8. `ServerList::SaveServerCache` serialises server-supplied strings
(`hostname`, `mapname`, `gametype`, `mod`, `version`) straight into the cache file, so one server advertising a
name in a legacy code page took the client down while saving the online-browser cache. This is a robustness /
hostile-input fix, so per the task rules it wins as-is.

The vendored library is `nlohmann/json` v3.11.2 (`deps/json`, submodule `bc889afb`), which has the
`dump (indent, indent_char, ensure_ascii, error_handler)` overload and `error_handler_t::replace` - the call
compiles against what we ship (proven below, not assumed).

## Conflicts and how they were resolved

**None.** `git merge r5168` merged clean with the `ort` strategy:

```
Auto-merging src/Components/Modules/ServerList.cpp
Merge made by the 'ort' strategy.
 src/Components/Modules/ServerList.cpp | 7 ++++++-
 1 file changed, 6 insertions(+), 1 deletion(-)
```

Both sides do edit `ServerList.cpp`, but ~210 lines apart and for different reasons: ours is a comment at the
fake-server filter (`947`: `// Servers with more than MAX_CLIENTS players ...` above the
`> Game::MAX_CLIENTS` check, which we raised from 18 to 32), upstream's is the cache write at `742`. No
overlap, so nothing to hand-resolve.

Verified the merge neither lost fork-side work nor smuggled in anything else:

```
git diff --stat HEAD^1..HEAD   ->  src/Components/Modules/ServerList.cpp | 7 ++++++-   (only upstream's hunk)
```

and our hunk is still there after the merge (`grep -n MAX_CLIENTS src/Components/Modules/ServerList.cpp` ->
lines 947/949, both using `Game::MAX_CLIENTS`, which is `constexpr std::size_t MAX_CLIENTS = 32` in
`src/Game/Functions.hpp`).

## New 18-slot sites in upstream's code, and what was done for 32

**None.** The whole incoming diff is the `dump ()` call - no array, no loop over clients, no `< 18` /
`MAX_CLIENTS` comparison, nothing that carries a per-player index. The cache entries it writes are per-server,
not per-player, and the two per-server player-count fields (`clients`, `maxClients`) are `int`s that we already
accept up to 32 (the fake-server filter uses `Game::MAX_CLIENTS` = 32, so a 32-slot server is not dropped).
Nothing to change for 32 players in this merge.

## Proof the fix actually changes behaviour (probe that can see a bad case)

`SaveServerCache` only runs with the online server browser open (`IsOnlineList()`, `ui_netSource == 1`), which
the LAN live test never reaches - so the live test cannot show this fix working. Instead the two `dump ()`
calls were run against the vendored header in isolation
(`.scratch/json_dump_probe.cpp`, not part of the build, rebuilt with
`g++ -std=c++17 -I deps/json/include .scratch/json_dump_probe.cpp -o .scratch/json_dump_probe`):

```
old  dump(): threw [json.exception.type_error.316] invalid UTF-8 byte at index 4: 0x20
new  dump(): returned 94 bytes, contains U+FFFD: yes
verdict: PASS (the fix is the difference: old throws, new writes the cache)
```

The input is a cache root with one entry whose `hostname` is `"Caf\xE9 LAN \xC0\xFF"` (cp1252 bytes, invalid
UTF-8). The probe is only trustworthy because it distinguishes the two calls: the pre-merge call is the "bad
case" and it visibly fails, the post-merge call writes the cache with U+FFFD replacements. Exit code 0 only
when old-throws AND new-writes AND the output carries the replacement character.

## Live test (the real game, 32-slot server, 27 bots + a client + a forced map change)

`python3 tools/aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll --bots 27 --client --minutes 5 --map-change-at 2`
-> **PASS 13/13**. Run twice on the same DLL; the summary line is identical both times (28/28 players, client
slot 27 before and after, mp_rust -> mp_crash, rejoin 72 s, 0 crash dumps):

```
server_alive, no_new_crash_dumps (0 new minidumps), players_in (28 of 28), client_slot_32 (slot 27 >= 18),
client_in_before, map_changed (mp_rust -> mp_crash), session_restarted (bot guids before ['bot0','bot1']..27
vs after ['bot27','bot28']..27), client_rejoined, rejoin_within (72 s, limit 150 s), rejoin_slot_32 (slot 27),
client_process_up, client_follow_line (1 'Server changing map mp_crash'), players_back_after (28 of 28)
PASS {'players_max': 28, 'players_wanted': 28, 'client_slot': 27, 'maps_seen': ['mp_crash', 'mp_rust'],
      'polls': 9, 'client_follow_lines': 1, 'iw4x32_marker_lines': 1, 'new_crash_dumps': 0}
```

The server console still carries `IW4x32: patched the stock iw4x.exe (md5 9c42ffa4...) - 14 arrays, 701
operands, 85 code patches (27 layout sites), 14 hooks - 32 players en...`, so the 32-player engine patch still
applies to the stock exe with this DLL. The three `Adding channel: error` lines in the console tail are the
stock exe's voice-channel setup under Wine (the string is in no file under `src/` or `iw4x32/`) and were
already there before the merge - not a regression.

Both live runs used the DLL built above. A rebuild from the same sources gives a different file hash (MSVC
under msvc-wine is not byte-reproducible - the second build of this tree produced `b83b4490aa182218e146fbf7ecfb1e67`
with the same size and the same REVISION), so do not chase an md5 mismatch between rounds.

Harness self-check (the probe-sees-a-bad-case proof for the live test itself):
`python3 tools/aiboi_test.py --self-test` -> `ok - 11 checks: good transcript passes, 0 wrong`.

## Box / worktree notes (not code)

- This worktree started with every submodule uninitialized. `build_iw4x_fork.sh` seeds them from the main
  checkout's clones, but that checkout has no `deps/companion` clone (it was added by upstream in the r5167
  sync), so the seeded `git submodule update --init -q` exited 1 with the `-q` hiding the reason and the build
  died with an empty log. Running the same command without `-q` showed it, and pointing
  `submodule.deps/companion.url` at the r5167 worktree's local companion clone (set in this worktree's local
  git config only) let it seed offline. All 14 submodules are checked out now, so the build script skips the
  step (`deps/zlib/zlib.h` exists).
- Nothing was fetched from the network; the upstream remote was only ever fetched from, never pushed to.

## What a human should test

1. **The actual fix**: open the online server browser on a client with this DLL, let it fill and save the cache
   (`servers.json` under the IW4x data dir), with at least one server whose name has non-UTF-8 bytes (a name
   typed in cp1252, e.g. an accented letter). Before: the client crashed on save. Now: the save succeeds and the
   bad bytes come back as U+FFFD in the list. The LAN test cannot cover this (cache save needs the online list).
2. **32-slot servers still survive the cache round-trip**: join/browse a 32-slot server, quit to the browser,
   re-open it - the 32-slot server should still be listed after the cache reload (our `Game::MAX_CLIENTS = 32`
   filter, upstream's write path unchanged in behaviour).
3. Release-time work carried over from the r5167 round and still open: cut the kit with
   `iw4x32/tools/make_latest.py --iw4x r5168` (the repo-root `latest.json` still says `r5154` and is generated
   per kit), regenerate `iw4x32/release/files/iw4x.dll` + `SHA256SUMS.txt`, and eyeball Discord rich presence
   on a 32-slot server (`partySize`/`partyMax` should read e.g. 28/32) - none of that is a CHECK.

## Open questions

- Other `dump ()` call sites still use strict mode (`Chat.cpp` muted list, `Bans.cpp` ban list, `Node.cpp`
  node list, `ServerList.cpp` favourites, `Download.cpp`, `Theatre.cpp`, `ServerDemo.cpp`, `GSC/ScriptStorage`).
  I read each: they serialise local or numeric/IP data (favourites store `address` strings only, nodes store
  addresses), so none takes a server-supplied name and none can throw the way the cache did. Left alone - it is
  upstream's call to harden them, and changing them here would be silent divergence from upstream.
- Upstream's `snapshot_s` still holds `clients[18]` and we do not grow it (no snapshot array in
  `engine_patches.json`). Unrelated to this commit; still the same open item as the r5167 round logged
  (`SetClientMatchData("players", "18".."28")` errors at match end).

NEXT ROUND: no - all three CHECKs pass on the merge commit `a4b1b214`: `r5168` is an ancestor of HEAD, the fork
builds clean with REVISION 5168, and the live 27-bot + client + map-change test passes 13/13 twice with the
client in slot 27 and 0 crash dumps. The merge had no conflicts and the incoming commit contains no 18-player
site, so there is no follow-up that could change a CHECK result. What is left is human/release work (items 1-3
above).

The report of the previous sync round (r5167) is archived at `runs/QWEN_REPORT-r5167-sync-archived.md`, and the
map-change rejoin task's report before that at `runs/QWEN_REPORT-mapchange-rejoin-archived.md`.
