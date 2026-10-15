# QWEN_REPORT — the rejoin verdict: say what happened, not "slot 8"

Task: `tools/aiboi_test.py` judged the map-change rejoin by a slot number, which conflates two different things
(the client-side 32-player layout gap vs a client that does not come back). Rework the rejoin case so it reads
the server and client console logs and reports what actually happened, and make the slot requirement its own
clearly named check.

## 0. Baseline (before any change)

| CHECK | result |
|---|---|
| `python3 tools/aiboi_test.py --self-test` | `[self-test] ok - 11 checks: good transcript passes, 0 wrong`, rc 0 |
| `bash $HOME/Projects/IW4x-32/tools-re/build_iw4x_fork.sh . Release` | PASS - `build/bin/Win32/Release/iw4x.dll`, 3864064 bytes, 4m29s. The worktree's submodules were not initialised and the script's `submodule update --init -q` exits 1 printing nothing (known from the previous round); running the same command without `-q` fetched all 14 deps from the main checkout's local clones, then the build ran clean. |
| live rejoin run | see §4 (in progress) |

## 1. What the logs actually contain (read off a real run before writing the probe)

A passing live run's logs (28 bots + client, `mp_rust` -> `mp_crash`) were read line by line. Both game processes
log into the **same** `userraw/console_mp.log*` set: the client rotates the file when it starts, so the server's
lines end up in `console_mp.log.000` and the client's in `console_mp.log`. Each file begins with the command line
of the process that wrote it - `-dedicated` vs the `iw4x://` join - which is what tells them apart. The engine
stamps every console line with ms since that process started and the file is append-only, so the lines are in
event order and the reload timings come off the client's own clock (no clock mapping between the two processes).

The client's side of a rejoin that worked (`mp_rust` -> `mp_crash`), verbatim:

```
[    144405] Server changing map mp_crash, gametype dom      <- the server's notice reached it
[    144412] Loading fastfile mp_crash_load
[    145664] Unloaded fastfile mp_rust
[    145671] Loading fastfile mp_crash
[    156402] Setting state to CA_LOADING in CL_DownloadsComplete
[    156402] Setting state to CA_LOADING in CL_InitCGame      <- it took the new level's game state
[    160822] CL_InitCGame:  4.42 seconds                      <- cgame init done: it is in the new level
[    160822] Com_TouchMemory: 0 msec. Using sum: 1513413627
```

Notes that changed the design:

* A normal map-change rejoin prints **no** `Disconnecting`/`Connecting` line on the client. `CL_Disconnect called
  for local client 0` appears once, at startup, before the first join - so a drop is only meaningful **after** the
  map-change notice. The failure signature the field log has is `Disconnecting from <addr> (@XBOXLIVE_PARTYENDED)
  at time N` and then silence.
* `Modifying session in CG_ParseServerInfo() to have 32 public and 0 private slots` (the fork's layout line) is
  printed on the **first** serverinfo parse only, not after a level reload - it cannot be the rejoin signal.
* Every run has benign `Error:` lines (`Could not load menufile "ui_mp/scriptmenus/kickplayer.menu"`, `Could not
  load material "gradient_slow_fadein"`) and one `Adding channel: error` (voice, under Wine). They are counted and
  named, never a failure.
* The server's side of the same story: `Client 0 connecting with 100 challenge ping from ...` and
  `Going from CS_FREE to CS_CONNECTED for  (num 28 guid "<human guid>")` - the slot the server handed the human,
  before and after the change. Bots get `bot<N>` guids, so the human's lines are separable from the bots'.
* The server's `-stdout` copy lags badly (block-buffered, last chunk lost when it is killed); its
  `console_mp.log.000` is current. The harness reads the server's story from both.

## 2. Plan

1. Fetch the client's and the server's console lines (filtered to the events that matter, on the box, so only a
   few hundred lines cross the wire), sort them by owner with the command-line marker, and parse them into a
   "story": notice seen, session dropped (with the `@REASON`), game state taken, level finished, error lines
   split into session-ending and known-benign, plus the server's slot handouts and level restarts.
2. Rebuild the rejoin checks in the order the story happens, so the first failure names what went wrong:
   `client_in_before`, `map_changed`, `session_restarted`, `client_followed_change`, `client_reconnected`,
   `client_loaded_map`, `client_no_session_error`, `client_process_up`, `client_high_slot_after`,
   `players_back_after`.
3. Every check carries a plain-words `reason`; the last line of the run is
   `FAIL - <first reason> | slots: 28 before the change, None after (high-slot coverage >= 18: not met)` - the
   slots are context on the right of the bar, never the reason. PASS prints the reconnect and load times.
4. Slot coverage is its own check, before the change (`client_high_slot`) and after it
   (`client_high_slot_after`), with the reason text saying it is a layout gap and not a reconnect failure.
5. `--self-test` gains the recorded transcripts for the three cases the task names (rejoin + reinit PASS;
   disconnect and never return; reconnect but never finish loading), plus the low-slot case asserting that the
   rejoin checks pass and the verdict does not talk about reconnecting, a no-client-log case, a notice-never-
   received case, a session-never-restarted case, and the log-owner split. The transcripts are the real run's
   event lines with the file lists and dvar dumps dropped - no box paths, no IPs.
6. Re-run all three CHECKs.

## 3. What is done

* `tools/aiboi_test.py`: the whole judging half is rebuilt as described (`console_events`, `client_story`,
  `server_story`, `rejoin_facts`, `split_logs`, `fetch_logs`, `verdict_line`, `chk(..., reason)`), the rejoin
  checks are in story order, slot coverage is split out, and the self-test is 16 checks over the recorded
  transcripts. `[self-test] ok - 16 checks: good transcript passes, 0 wrong`, rc 0.
* The three verdicts the task asks to prove, as the harness now prints them:

```
PASS - the client followed the change to mp_crash, reconnected after 20 s and finished loading it 16 s after
       the notice | slots: 28 before the change, 28 after (high-slot coverage >= 18: met)
FAIL - client did not reconnect within 150 s after the map change - it left the session with
       @XBOXLIVE_PARTYENDED and stayed out | slots: 28 before the change, None after (high-slot coverage: not met)
FAIL - client reconnected but never finished loading mp_crash - its console shows no game state and no cgame
       init for the new level | slots: 28 before the change, 28 after (high-slot coverage >= 18: met)
```

* and the case that used to read as a rejoin failure:

```
FAIL - the client is back but in slot 3, below 18 - the 32-player layout did not survive the reload
       (a layout gap, not a reconnect failure) | slots: 28 before the change, 3 after (...)
       (client_reconnected, client_loaded_map and client_no_session_error all ok)
```

## 4. CHECK results

| CHECK | result |
|---|---|
| `--self-test` | `[self-test] ok - 16 checks: good transcript passes, 0 wrong`, rc 0 |
| build | PASS (unchanged from baseline - this task touches no C++; dll rebuilt at baseline, 4m29s) |
| live rejoin run, high-slot client | in progress |
