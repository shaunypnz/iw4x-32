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
* `server_story()` now returns `restart_ms` (last level restart) and `handshake` — the human guid's
  `CS_FREE -> CS_CONNECTED` line **after** it, with the challenge ping beside it when one is stamped after the
  restart. It wants two restarts in the text: the client's first connect sits between them, and counting that as
  the re-connection would prove nothing.
* `reinit_sequence(cli, srv, playing, map_to)` builds the chain and finds the first break:
  `notice -> fastfile -> reinit -> layout -> loaded -> server_reconnect`. `loaded` counts as done on the cgame
  init line or, when neither console copy flushed that far, on the usercmds the server gets from the client (the
  same two witnesses `client_loaded_map` uses, so the chain cannot fail where that check legitimately passes).
  When every step is present, the stamped client steps must also be in engine order — a step stamped before the
  one that must precede it belongs to the first join, not to the rejoin. The layout line is deliberately not
  ordered: the real run prints it 1 ms after the game-state line, either side of it is fine.
* New check `client_reinit_sequence` in `case_rejoin`, placed after `client_loaded_map` so the specific checks
  still name their own failures first. Its detail prints the whole chain with the client's own offsets; its
  reason names the first step that broke. The PASS verdict line now carries the chain too, and the live run's
  report dict gained `client_reinit_chain` / `client_reinit_gap`.
* Transcripts: `cli_log(layout=False)` and `srv_log(handshake=False)` build the two bad chains; the real run's
  layout line is in `CLI_BOOT` and after the notice, where the live log has it.

## 4. Proof the new check sees a bad case (`--self-test` 22 checks, rc 0)

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
                             reason: broke at 'server_reconnect': the server never handed the human guid a
                             slot again after its level restart   (status still shows the client in slot 28)
re-init out of order    FAIL reason: broke at 'loaded': its own console stamps it at 140000 ms, before
                             'notice' at 144405 ms - those lines belong to the first join, not the rejoin
never rejoins           FAIL notice -> fastfile -> reinit MISSING -> layout MISSING -> loaded MISSING -> ...
console stops mid-load  ok   ... loaded(usercmd) ... (the server's usercmd witness, as in the live runs)
stdout copy only        ok   chain judged on presence, no offsets invented
```

The chain check moves on every bad case and stays quiet on the good ones, and the pre-existing verdicts are
unchanged (`client did not reconnect within 150 s`, `never finished loading mp_crash`, `slot 3`, ...).

## 5. Live run (does the chain exist in real logs?)

In progress — the new required steps are read from real console lines, so one live run with `--save-logs` checks
the chain against a real `mp_rust -> mp_crash` rejoin before this is handed back.
