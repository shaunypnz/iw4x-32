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
