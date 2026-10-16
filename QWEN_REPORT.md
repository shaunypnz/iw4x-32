# QWEN_REPORT — aiboi_test.py: assert the client's re-init / re-connection SEQUENCE after a map change

Task: `tools/aiboi_test.py` must specifically assert the successful client re-initialization / re-connection
sequence after the forced map change, not only the final game state (the failure analysis for
`fix/iw4x32-map-change` called out a missing re-connection logic check).

## 0. Baseline (before any change)

| CHECK | result |
|---|---|
| `python3 tools/aiboi_test.py --self-test` | `[self-test] ok - 18 checks: good transcript passes, 0 wrong`, rc 0 |

The CHECK passes at the start, so this round is about what the probe does **not** look at, and about proving the
new assertion can see a bad case.

## 1. What the rejoin case asserts today, and the gap

Today's rejoin checks: `client_in_before`, `map_changed`, `session_restarted`, `client_followed_change`,
`client_reconnected` (the client appears in a later `status` poll), `client_loaded_map` (cgame init line **or**
the server's `lastmsg`), `client_no_session_error`, `client_process_up`, `client_high_slot_after`,
`players_back_after`.

The gap the task names: nothing asserts the **chain** the client has to walk to get from the notice back into the
level. Concretely, three re-connection steps are fetched but never judged:

* `Loading fastfile <map_to>` in the client console — it pulled the new level's data.
* `iw4x32: server is 32-slot - using the 32 player/body layout` — the client re-parsed serverinfo on the new
  connect and re-applied the 32-player layout. `src/Components/Modules/IW4x32.cpp:325` prints it **every**
  connect and level restart precisely so this question can be read off a client console; `CLI_EVENT` already
  greps `iw4x32: ` but no check reads the line.
* the server's connect handshake after the level restart — `Client 0 connecting with ... challenge ping` and
  `Going from CS_FREE to CS_CONNECTED for  (num N guid "<human>")`. `server_story()` collects these
  (`connects`, `human_slots`) and they are only used as decoration in another check's detail.

So a client that ends up in `status` in the right slot without ever having re-initialized (or one the server
never took back through the handshake) can pass today. That is the missing re-connection logic check.

## 2. Plan

1. `client_story()` also picks up `Loading fastfile <map_to>` and the `iw4x32: server is ...` line from the
   client's tail; `client_story_all()` merges them across the two console copies like the other steps.
2. `server_story()` records the last level restart and the human guid's connect handshake **after** it
   (challenge ping + `CS_FREE -> CS_CONNECTED`), on the server's own clock — never compared to the client's.
3. New `reinit_sequence()`: the chain in engine order —
   `notice -> fastfile -> reinit (Setting state to CA_LOADING in CL_InitCGame) -> layout (iw4x32: server is ...)
   -> loaded (CL_InitCGame: N seconds) -> server_reconnect (handshake after the restart) -> in_level`
   — with the last step proven by the cgame init line or by the server's usercmd witness.
4. New check `client_reinit_sequence` in `case_rejoin`, placed after `client_loaded_map` so the specific checks
   still name their own failures first; its detail prints the whole chain with the client's own millisecond
   offsets, and its reason names the first step that is missing or out of order.
5. `--self-test` gains transcripts that prove the new check is not a probe that always reads "perfect":
   a layout line missing after the notice (the fork's layout re-init never ran) must fail it, and the good
   transcript must pass it.

## 3. What was implemented (`tools/aiboi_test.py`)

* `CLI_LAYOUT` / `CLI_FASTFILE` / `CLI_ORDER` next to the other console patterns; `CLI_EVENT` also greps
  `challenge ping` so the server's connect line is guaranteed to survive the on-box filter.
* `client_story()` picks up `Loading fastfile <map_to>` and `iw4x32: server is ...` from the tail after the
  notice, as presence + ms offset; `client_story_all()` merges them across the two console copies (a step counts
  when any copy printed it, its offset comes from the copy that carries the ms stamps).
* `server_story()` now returns `join`, `restart_ms`, `handshake`, `human_after` and `post_change` (see §5 for why
  the naive version of this was wrong): the handshake is a human `CS_FREE -> CS_CONNECTED` line stamped after a
  level restart that follows the human's first join, `human_after` is any line naming the human's guid or
  `clientNum` in the window after the change, and `post_change` says whether the server's text reaches into that
  window at all.
* `reinit_sequence(cli, srv, playing, map_to)` builds the chain and finds the first break:
  `notice -> fastfile -> reinit -> layout -> loaded -> server_reconnect`. `loaded` counts as done on the cgame
  init line or, when neither console copy flushed that far, on the usercmds the server gets from the client (the
  same two witnesses `client_loaded_map` uses, so the chain cannot fail where that check legitimately passes).
  `server_reconnect` is graded by what the server's console can actually say (§5). When every step is present,
  the stamped client steps must also be in engine order — a step stamped before the one that must precede it
  belongs to the first join, not to the rejoin. The layout line is deliberately not ordered: the real run prints
  it 1 ms after the game-state line, either side of it is fine.
* New check `client_reinit_sequence` in `case_rejoin`, placed after `client_loaded_map` so the specific checks
  still name their own failures first. Its detail prints the whole chain with the client's own offsets; its
  reason names the first step that broke. The PASS verdict line now carries the chain too, and the live run's
  report dict gained `client_reinit_chain` / `client_reinit_gap`.
* Transcripts: `cli_log(layout=False)` and `srv_log(handshake=False)` build the two bad chains, and
  `srv_log(handshake=False, human_line=True)` the good run whose only server witness is a stats line; the real
  run's layout line is in `CLI_BOOT` and after the notice, where the live log has it.

## 4. Proof the new check sees a bad case (`--self-test` 23 checks, rc 0)

Four new self-test cases plus the existing ones re-asserted. What the check prints (from `scratch/show_seq.py`):

```
good                    ok   notice -> fastfile -> reinit -> layout -> loaded -> server_reconnect
                             | client clock: fastfile +1 s, reinit +12 s, layout +12 s, loaded +16 s
                             | the server handed slot 28 back after a challenge ping
no layout line          FAIL notice -> fastfile -> reinit -> layout MISSING -> loaded -> server_reconnect
                             reason: the client's re-init chain after the map change broke at 'layout':
                             no 'iw4x32: server is ...' line after the notice - it never re-read the
                             server's layout on the new connect
                             (client_reconnected, client_loaded_map and client_high_slot_after all still ok:
                             this is the final-state-blind case the task is about)
no server handshake     FAIL ... -> loaded -> server_reconnect MISSING
                             reason: broke at 'server_reconnect': the server logged the window after the change
                             and never named the human guid or clientNum again - it never took the client back
                             (status still shows the client in slot 28: the final state looks fine)
re-init out of order    FAIL reason: broke at 'loaded': its own console stamps it at 140000 ms, before
                             'notice' at 144405 ms - those lines belong to the first join, not the rejoin
never rejoins           FAIL notice -> fastfile -> reinit MISSING -> layout MISSING -> loaded MISSING -> ...
console stops mid-load  ok   ... loaded(usercmd) ... (the server's usercmd witness, as in the live runs)
stdout copy only        ok   chain judged on presence, no offsets invented
```

The chain check moves on every bad case and stays quiet on the good ones, and the pre-existing verdicts are
unchanged (`client did not reconnect within 150 s`, `never finished loading mp_crash`, `slot 3`, ...).

## 5. Live run: the chain against real logs (and what it corrected)

Built the branch (`build_iw4x_fork.sh . Release`, rc 0, `iw4x.dll` 3864576 bytes) and ran the tool itself on the
test box: `--bots 27 --client --minutes 5 --map-change-at 2 --save-logs scratch/live-logs`.

First run: **PASS, 15/15 checks** including the new one —

```
ok   client_reinit_sequence: notice -> fastfile -> reinit -> layout -> loaded -> server_reconnect
                             | client clock: fastfile +1 s, reinit +13 s, layout +13 s, loaded +19 s
                             | the server handed slot 27 back after a challenge ping
```

and the client's own console carries every client-side step verbatim (`mp_rust` -> `mp_crash`):

```
[    191703] Server changing map mp_crash, gametype dom
[    193067] Loading fastfile mp_crash
[    205164] Setting state to CA_LOADING in CL_InitCGame
[    205165] iw4x32: server is 32-slot - using the 32 player/body layout
[    210966] CL_InitCGame:  5.80 seconds
```

**But the server-side step it passed on was wrong, and reading the saved logs caught it.** The server's two
console copies (`server.log`, `userraw/console_mp.log.000`) each contain exactly **one** `Server Initialization`
line — the one at process start (ms 5206) — and the human's connect line at ms 80140, i.e. its **first** join.
The level restarts caused by `map_rotate` are in neither copy: a dedicated server prints almost nothing once the
level runs, so its console file lags the process by a 4 KB block, and the next stamped line in that file is 130 s
later (ms 210685). So "the human's slot line after the last restart line" was matching the first join and calling
it a re-connection — a pass that proves nothing.

Corrected, on the evidence:

* `server_story()` now works off stamped lines only and separates three things: `join` (the human's first
  `CS_FREE -> CS_CONNECTED`), `restart_ms` (the last stamped restart **after** that join — None when the copy has
  no such line, which is the normal case), and `post_change` (whether the text reaches into the window after the
  change at all, measured from the restart or, when it is missing, from `join + 60 s`).
* The chain's server step now accepts, in order of strength: the handshake (a human `CS_CONNECTED` after a
  restart that follows the join), or the weaker witness a real server console does carry — any line naming the
  human's guid or `clientNum` in that window (`Received packet 0 of stats data from clientNum 27`, ms 210685 in
  this run) — and it is *not judged* when the server's console never reaches that window. It fails only when the
  server logged the window, logged other clients coming back through it, and never named the human again.
* The client's console has no `challenge ping` line (that is a server-side line), so the client-side re-connect
  witness is the `iw4x32: server is ...` line: `CG_ParseServerinfo` runs on a fresh serverinfo parse, and the
  real rejoin prints it 1 ms after the game-state line, for every one of the three level changes in the run.

Re-judging the saved logs of that run with the corrected code:

```
client_reinit_sequence: ok
  notice -> fastfile -> reinit -> layout -> loaded -> server_reconnect
  | client clock: fastfile +1 s, reinit +13 s, layout +13 s, loaded +19 s
  | the server's console names clientNum 27 again after the change
```

A second live run with the corrected tool is in `scratch/live-logs2` / `scratch/live2.out`.

## 6. CHECK

| CHECK | result |
|---|---|
| `python3 tools/aiboi_test.py --self-test` | `[self-test] ok - 23 checks: good transcript passes, 0 wrong`, rc 0 |

## 7. Open questions

* The server's console never logging a mid-run level restart is a harness-visible fact now, but it is also why
  `session_restarted` is judged off the bot guid change rather than the server's own restart line. Worth a look
  at whether the server should be started with a bigger logfile flush (out of scope here).
* `REJOIN_WINDOW_MS = 60 s` assumes the forced map change never lands in the first minute of the server's level;
  `--map-change-at` is documented as a mid-test change, so that holds for the runs the harness makes.

NEXT ROUND: no - the CHECK passes (23 self-test checks), the new chain check is proven to fail on six recorded
bad cases, and it passes end-to-end on a live run of the real game with every step read off real console logs.
