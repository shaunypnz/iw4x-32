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

## 4. Round 3: why the live run failed `client_loaded_map`, and what the fix is

The last live run failed one check and one only:

```
FAIL client_loaded_map: no 'Setting state to CA_LOADING in CL_InitCGame' + 'CL_InitCGame: N seconds' pair after
the notice; it got as far as +13 s (game state) and stopped
```

**It is a measurement artifact, not a client that failed to load.** The evidence is in `scratch/probe-out/`
(the instrumented probe the last pass left behind in `scratch/`, untracked - one run on the box, 27 bots +
client, `mp_rust` -> `mp_crash`, sampled every 5-8 s; its numbers are quoted here):

* the client's `userraw/console_mp.log` sat at **108730 bytes from +166 s to +300 s** of that run while the client
  was demonstrably still printing (its `-stdout` copy grew 20413 -> 24192 -> 25562 bytes over the same window).
  The file only ever grows in steps of ~4150 bytes: the game writes its console through a 4 KB stdio buffer and
  flushes when the buffer is full. A level reload prints its `CL_InitCGame: N seconds` line and then goes quiet,
  so that line is the first thing left sitting in the process and missing from the file. The failing run's client
  console ends **mid-line** (`Error: Could not load menuf`) - the buffer boundary, caught in the act.
* the post-change line was there all along in the client's `-stdout` copy (`client.log` line 491, `CL_InitCGame:
  5.58 seconds`, present from +174 s on) - the harness never read that copy because the client was not started
  with `-stdout`.
* the probe's `say`-flood question is answered too: 60 `say` lines over rcon took the client's console log from
  108730 to **112892** bytes and the missing line appeared in it (`2274:[ 95373] CL_InitCGame:  5.58 seconds`).
  Making the client print is how you get its own buffer onto the disk. Killing it does nothing (sizes unchanged
  after SIGTERM).
* the server-side witness the probe was also asking about: the human's `status` row reads `lastmsg 0` while it is
  in the level and `lastmsg 11400` (ping 999) once its process is gone. A client on a loading screen sends no
  usercmds, so `lastmsg` is an independent witness that it finished loading - and it moves.

Fixes, in this order:

1. start the client with `-stdout` and read **both** copies of its console; the story is what the copies say
   together (each one lags the process by whatever it has not flushed, so a line missing from one proves nothing).
2. before fetching the logs, push `say` lines over rcon so the client flushes its own console log.
3. `client_loaded_map` accepts the console pair as the primary proof and the server's `lastmsg` as the secondary
   one, and says which one it used; it fails only when neither is there, with both numbers in the reason.
4. `Server changing map (\w+)` - the old `(\S+)` captured `mp_crash,` with the comma, so the notice never matched
   `map_to` and the code silently fell back to "the last notice whatever map it names".

## 5. CHECK results

| CHECK | result |
|---|---|
| `python3 tools/aiboi_test.py --self-test` | `[self-test] ok - 18 checks: good transcript passes, 0 wrong`, rc 0 |
| `bash $HOME/Projects/IW4x-32/tools-re/build_iw4x_fork.sh . Release` | PASS - `iw4x.vcxproj -> ...\build\bin\Win32\Release\iw4x.dll` (this task touches no C++; rebuilt anyway) |
| live run `--bots 27 --client --minutes 5 --map-change-at 2` | **PASS**, 14/14 checks |

The live run (t1792098949, 9 polls):

```
ok   client_followed_change: 2 'Server changing map' line(s) in the client console, last one for mp_crash
ok   client_reconnected: back in status 72 s after the change (limit 150 s); the server handed the human guid slot 27 again
ok   client_loaded_map: took the new level's game state 11 s after the notice and was in mp_crash 17 s after it
                                    (cgame init 5.59 s)
ok   client_no_session_error: 0 session-ending error line(s) after the change; 3 known-benign error line(s)
PASS - the client followed the change to mp_crash, reconnected after 72 s and finished loading it 17 s after the
       notice | slots: 27 before the change, 27 after (high-slot coverage >= 18: met)
```

The line the last run could not find is there now, and the flush is what put it there:

```
[    202745] Setting state to CA_LOADING in CL_InitCGame
[    202746] iw4x32: server is 32-slot - using the 32 player/body layout
[    208330] CL_InitCGame:  5.59 seconds
```

`client_console_copies: 2` in the report dict says both copies of the client's console were read; the `say` flood
ran before the fetch, so the tail of the file is the tail of the story rather than the tail of a 4 KB block.

## 6. What the self-test now covers (18 checks)

The rejoin transcripts, all judged by the same code the live run uses:

* good: notice -> reconnect -> cgame init, in both copies of the console (timed), and in the stdout copy only
  (untimed - that copy carries no ms stamps, and the verdict says so instead of inventing a number)
* good: the console copies stop mid-reload but the server still gets a usercmd every frame - the check passes on
  that witness and names it
* bad: reconnects but never loads - **both** witnesses have to say so (no cgame init line in either copy AND
  `lastmsg` 45000 ms), which is what keeps a lagging log file from failing a healthy client
* bad: never comes back, comes back in a low slot, no client console log at all, no level restart, bots not
  re-added, same map after the change, session-ending error after the change, client process gone
* plus the baseline transcripts and the two parsers, `split_logs` (three blocks in, three stories out) and
  `parse_status` over the real `status` text

## 7. Notes for the next reader

* `client_loaded_map` is deliberately the third check, after `client_reconnected`: the task lists the story in
  that order (disconnect, reconnect, finish loading, error, slots) and the verdict names the first thing that
  failed in it. A client that never came back is reported as that, not as a load failure.
* `PLAYING_MIN_S = 30` exists because `lastmsg` is small during the join handshake too (50 ms in a recorded
  snapshot taken mid-join): only a poll well after the change can tell "in the level" from "negotiating".
* the probe that measured all this is in `scratch/` (untracked, run once, cleaned the box up after itself);
  `scratch/probe-out/probe.log` has the per-5-second samples behind the numbers quoted above.
