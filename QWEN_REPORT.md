BROKEN CHECK: `python3 $HOME/Projects/IW4x-32/tools-re/aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll --bots 8 --client --minutes 5 --map-change-at 2`

- The pass rule needs `client_slot >= 18`. The test spawns the `--bots` bots **before** the client and the
  engine gives a connecting client the lowest free slot, so with `--bots 8` the client is in **slot 8** - in
  every build, whatever the code does. Re-measured against the round-5 build:
  `FAIL {'map_changed': True, 'players_after_map_change': 9, 'server_alive': True, 'players_max': 9, 'players_wanted': 9, 'new_crash_dumps': 0, 'client_slot': 8}`
  - every criterion passes except the slot rule. Nothing in this worktree can move that slot.
- The bug itself only exists for a client in a slot >= 18 (the stock party/session layer is 18 members wide),
  so the test also needs enough bots to push the client out of that layer. **Working form:**
  `python3 $HOME/Projects/IW4x-32/tools-re/aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll --bots 28 --client --minutes 5 --map-change-at 2`
  -> `PASS {'map_changed': True, 'players_after_map_change': 29, 'server_alive': True, 'players_max': 29, 'players_wanted': 29, 'new_crash_dumps': 0, 'client_slot': 28}`
- Second problem with the CHECK, not fixable from inside this worktree: its 5-minute window is shorter than
  the failure. In the runs that reproduced it the client followed the change, came back, and only then walked
  out - 427 s, 479 s and 720 s later. `iw4x32/tools/mapchange_rejoin.py` (added this round) is the 12-minute
  form of the same scenario.

---

# Round 5 (2026-10-14) - the fix narrowed to one hook, and every way to print that last console line

**What changed: the `0x4B6010` disconnect-reason hook from round 4 is gone; the `0x5028B0` party host timeout
hook stays. Same protection against the field failure, without swallowing a LAN client's real disconnect
reasons.** New DLL md5 `debf8fe5165a39463af0b2c441f4730a`.

## 1. Why the 0x4B6010 hook came out

Round 4 assumed the end-of-match rotation reaches the client with the fallback reason `EXE_SERVERKILLED`. It
does not - the senders were read this round:

- `SV_KillServer` (0x4F5BC0) is the only thing that broadcasts a reason to every client (`SV_BroadcastDisconnect`
  0x6260A0 -> `disconnect <reason>`). Its four callers are `SV_Cmd_quit_f` (0x4D4000, reason
  `EXE_SERVERKILLED`), the deferred restart handler (0x4806C0) and Com_Error cleanup (0x60BFD0, twice). **A map
  rotation is not one of them**, and neither is a match end: `SV_SetEndGameReason` (0x4CA1E0) only records
  `roundsdone` / `EXE_MATCHENDED` / `hostquit` / `EXE_MIGRATIONLIMIT` for the host-migration state machine.
- A level change runs `SV_SpawnServer` (0x4A7120): it sends `loadingnewmap\n<map>\n<gametype>` to every client
  in a state > 3 and drops the rest with `sendReason = 0`, i.e. with **no reason packet at all**. Measured with
  the round-4 fix compiled out: `rcon map mp_broadcast` at 2 min, the client reloaded mp_broadcast, came back in
  slot 28 and was still there 11 minutes later.
- So `EXE_SERVERKILLED` reaches a client only when the server process quits - which is what our own runner does
  at the end of every run. That is what the round-4 A/B actually stopped: the test's own `rcon quit`, not the
  field failure. (Same reason the "walk-out at 427 s / 479 s / 720 s" table in round 2 is an artifact.)
- What keeping the hook cost: for a LAN client in a game it skipped the whole handler, so
  `EXE_PLAYERKICKED...`, `EXE_MATCHENDED`, `EXE_SERVERQUIT` and the migration reasons stopped working too.

## 2. Every way the engine can print the field's last line

`0x40FF00` is the walk-out: `Disconnecting from %s (%s) at time %i`, live-session teardown,
`menu_xboxlive_lobby` / `menu_xboxlive_lobbyended` with `partyend_reason`. Its seven callers:

| caller | what it is | through 0x5028B0? |
|---|---|---|
| `0x5028B0` (3 sites) | the party host timeout handler | it *is* it |
| `0x413A70` | "leave the live session" - Com_Error cleanup (0x60BFD0, ERR_DROP / ERR_DISCONNECT), `Party_ClosePartyUI` (0x4C3A40), the `EXE_PLAYERKICKED` branch of the disconnect handler | no, but only ever after a Com_Error has already ended the game |
| `0x4B84D0` | party migration timeout (needs session+0x0C set) | no |
| `0x446980` | party migration cannot start | no |

Everything that can end a game that is **already running** out of the session layer reaches the walk-out
through `0x5028B0`:

| path | trigger |
|---|---|
| `0x4973A0` keepalive | `Host has timed out. Disconnecting from %s host` - 12 s without a party-host heartbeat, 4 consecutive checks (`0x46BC00` always returns 0, so nothing suppresses it). Reached from `0x407740` only when the session says the client is **not in a game** (session+0x17F0 == 0) while it is still in a live session (+0x17FC != 0). It prints nothing after the walk-out - the only path that leaves the walk-out as the last line of the client log, which is what the field log looks like. |
| `0x4E5090` -> `0x4C28D0` | the in-game session frame, when the session state changes |
| `0x4A7CA0` | the "party gone" helper: from the disconnect-reason handler (0x4B6010, for any reason the client does not know), from the client's own connection timeout (0x5A8DF0, `Server timed out. Connection state is %i. Migration state is %i.`), and from Com_Error cleanup (0x60BFD0) |

For a systemlink client `0x4A7CA0` is *nothing but* `call 0x5028B0`, so the one hook on `0x5028B0` covers all
three of its entry points as well as the keepalive and the in-game frame. That is the whole fix:

- `LanClientInGame()` - the `systemlink` dvar is on (`[0x649E714]+0x10`) **and** the local connection state is
  `CA_CONNECTING .. CA_ACTIVE` (`0xB2C540`, the same global IW4x reads in `Menus.cpp`).
- `PartyTimeout_Stub` at `0x5028B0` - return without running it. A LAN client hears from its server over plain
  UDP with its own timeout (`0x5A8E80` -> `0x5A8DF0`), so a party failure tells it nothing; a server that
  really goes away still drops it the normal way, with the normal error text.

Reasons a server can put in a `disconnect` packet, against what `0x4B6010` knows. Known: `EXE_MATCHENDED`,
`EXE_SERVERQUIT`, `EXE_MIGRATIONABORTED`, `EXE_MIGRATION_IN_PROGRESS`, `hostquit`, `EXE_PLAYERKICKED*`,
`roundsdone`, `XBOXLIVE_SIGNINCHANGED`. Unknown - they fall through to the party-gone helper and then to
`Com_Error(ERR_SERVERDISCONNECT)`: `EXE_TIMEDOUT` (`SV_CheckTimeouts` 0x4F6E80), `EXE_TRANSMITERROR`,
`EXE_LOSTRELIABLECOMMANDS`, `EXE_SERVERMESSAGEOVERFLOW`, `EXE_UNPURECLIENTDETECTED`,
`EXE_CANNOTVALIDATEPURECLIENT`, `EXE_DISCONNECTED`, `Too many stats changed at once` (0x4A1340, the per-client
stat flush overflowing its 1024-byte packet). None of them appears in any of our runs' logs.

## 3. Still not reproducible without probes - two more controls this round

Both with `.scratch/iw4x-nofix.dll` (round-4 fix compiled out), 28 bots, human in slot 28, 12 min,
`iw4x32/tools/mapchange_rejoin.py` (updated this round: `--map-to`, `--scorelimit`, `--endgame-at`, and it now
scp's `client.log` + `server.log` into `.scratch/<tag>/` so the tails stop being the only evidence):

| run | how the map changed | result |
|---|---|---|
| `rj-nofix` | `rcon map mp_broadcast` at 128 s | client followed, slot 28 on mp_broadcast, 13 min, no walk-out |
| `rj-endnofix` | `rcon set scr_dom_scorelimit 40` at 36 s - the match ended by itself: `==== ShutdownGame (1) ====`, `------ Server Initialization ------`, `iw4x32: 32-slot server - 32-player layout, patched clients only` at ~560 s | client followed, slot 28, clean to 12 min; `client.log` has **zero** `Disconnecting` / `timed out` / `EXE_` / `ERROR:` lines |
| `rj-end-fix` | same, with the shipped round-5 build | same: rotation at ~560 s, client in slot 28 in the last minute, 0 walk-outs, 0 crash dumps |

So a level change and a real end-of-match rotation do not reproduce it on this box. The one thing at match end
that does touch slots >= 18 and fails is the 18-wide session layer, and it is visible in the server log:

```
Error: In call to SetClientMatchData( "players", "18", "xuid", ... )     <- slots 18..28
Error: Unable to set last round results for client num: 25 ... 28
```

(`0x627500` -> `0x48CB10` returns -1 because the session member array is 18 wide, the same layer the five
0x12-bounded hooks keep slots >= 18 out of). It is not fatal here, but it is the match-end path failing on
exactly the slots this fork adds, and it is worth its own task.

## 4. CHECK, run against the shipped build (md5 `debf8fe5165a39463af0b2c441f4730a`)

```
aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll --bots 28 --client --minutes 5 --map-change-at 2
  PASS {'map_changed': True, 'players_after_map_change': 29, 'server_alive': True, 'players_max': 29,
        'players_wanted': 29, 'new_crash_dumps': 0, 'client_slot': 28}

aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll --bots 8 --client --minutes 5 --map-change-at 2   # as written
  FAIL {'map_changed': True, 'players_after_map_change': 9, 'server_alive': True, 'players_max': 9,
        'players_wanted': 9, 'new_crash_dumps': 0, 'client_slot': 8}
```

The `--bots 8` form fails on one criterion only, `client_slot 8 < 18`, in every build (the bots are spawned
before the client and the engine hands out the lowest free slot). The bug is a slot >= 18 bug, so the test has
to put the client past 18: that is what `--bots 28` does, and it passes.

---

# Round 4 (2026-10-14) - the fix, and what is and is not proven

**What changed: two client-side hooks in `src/Components/Modules/IW4x32.cpp` (+71 lines) stop the engine's
party/session layer from ending the game for a LAN client that is sitting in a slot >= 18. That layer is 18
members wide, so such a client is never registered with it, and the handler that notices ends the whole game
with `@XBOXLIVE_PARTYENDED` - the exact line the live report's client console dies on.**

## 1. The chain (read out of the stock exe with `gdec`)

```
0x4B6010  client disconnect-reason handler   <- "disconnect <reason>" from the server
  |        it knows hostquit / roundsdone / EXE_MATCHENDED / EXE_SERVERQUIT / EXE_PLAYERKICKED /
  |        XBOXLIVE_SIGNINCHANGED / ... ; hostquit and roundsdone are simply ignored (0x4B6160)
  v        an unknown reason falls through to
0x4A7CA0  "the party host is gone" helper (call at 0x4B60F7)
  v
0x5028B0  party host timeout handler. First bytes: mov eax,[0x649E714]; cmp byte [eax+0x10],0
          -> systemlink set: branch 0x5029B7 -> 0x40FF00(cl, reason, "@XBOXLIVE_PARTYENDED", 1) -> ret
  v
the client leaves the game and goes back to the menu. No Com_Error text, no crash dump. The server keeps the
slot until it drops the now-silent client with GAME_DROPPEDFORINACTIVITY - which is why the report reads as
"nobody reconnected".
```

`0x5028B0` has a second caller: the party keepalive at `0x4973A0`, which runs it once the client has gone quiet
towards the party host for 12 s. A slot >= 18 client is never registered with the session host at all (the five
0x12-bounded hooks from the previous round keep slots >= 18 out of the 18-wide session layer), so it is on that
timeout path from the moment it joins. Both paths end in the same handler, and for a systemlink client that
handler does nothing except end the game.

## 2. The fix (`src/Components/Modules/IW4x32.cpp`, marked `// IW4x-32:`)

One predicate, two hooks, same `__declspec(naked)` + `s_back_*` pattern as the rest of the component:

- `LanClientInGame()` - the `systemlink` dvar is on (`[0x649E714]+0x10`) **and** the local connection state is
  `CA_CONNECTING .. CA_ACTIVE` (`0xB2C540`, the global IW4x itself reads in `Menus.cpp`). A signed-in client,
  or one that is back at the menus, keeps the stock behaviour.
- `DisconnectReason_Stub` at `0x4B6010` - for such a client, ignore `EXE_SERVERKILLED` and return, which is
  what the handler's own `hostquit` / `roundsdone` path does. The game connection is plain UDP with its own
  timeout ("Server timed out", 0x5A8DF0), so a server that really goes away still drops the client normally.
- `PartyTimeout_Stub` at `0x5028B0` - for such a client, return without running the handler; its callers
  (keepalive 0x4973A0, party-gone 0x4A7CA0) carry on with their per-frame work.

## 3. What is proven, and what is not

Proven:
- The mechanism, from the disassembly above, and the fact that it is slot-dependent: round 1 ran the same
  scenario with 8 bots (human in slot **0**) and the client was clean at 714 s, while with 28 bots (human in
  slot 28) it walked out at 427 s / 479 s / 720 s in three runs.
- The hooks do what they say: with temporary probe hooks on the client, the chain
  `disconnect reason 'EXE_SERVERKILLED' -> party-gone from 004B60FC -> party-timeout from 004A7CE4 ->
  @XBOXLIVE_PARTYENDED` prints in full with the fix off (client time 537 s) and stops at the first line with
  the fix on, with the human still in slot 28 at 660 s.

**Not proven, and this is the honest part: we have not reproduced the field failure without the probes on.**
Two probe-free controls with the fix compiled out (`.scratch/iw4x-nofix.dll`, `mapchange_rejoin.py`, 28 bots,
human in slot 28) both stayed in the game for the whole window - 13 min with the match left to end by itself,
and 12 min with `rcon map_rotate` at 2 min. Worse, one reason the probe runs walked out is that the probe itself
was wrong: `SvEndGameProbe_Stub` at 0x4CA1E0 pushed `[esp+0x20]` after `pushad`, which is the **return address**,
not the reason argument (`[esp+0x24]`) - so probe builds corrupted the end-game reason and manufactured the
`EXE_SERVERKILLED` the client then choked on. The probe hooks are gone from the shipped code; the A/B above is
therefore a proof about the handler, not a reproduction of the report.

So the fix is aimed at the handler that printed the reported line, on a mechanism that is fully explained and
slot-dependent, but the next round still owes a clean before/after on the real symptom.

## 4. Test evidence (this round)

| run | build | probes | recipe | result |
|---|---|---|---|---|
| AB1 | fix off | yes | 28 bots, slot 28, match forced to end at 42 s | full chain -> `@XBOXLIVE_PARTYENDED` at client time 537 s |
| AB2 | fix on | yes | same | chain stops at the reason line, human in slot 28 at 660 s |
| MCR2 | fix off | no | 28 bots, slot 28, 13 min, match left alone | clean (the match never ended) |
| MCR3 | fix off | no | 28 bots, slot 28, 12 min, `rcon map_rotate` at 2 min | clean - no probe-free reproduction |
| CHECK live, working form | fix on | no | `--bots 28 --client --minutes 5 --map-change-at 2` | **PASS** (run twice against the shipped DLL), slot 28, 29 players before and after, 0 dumps |
| CHECK live, as given | fix on | no | `--bots 8 ...` | FAIL on `client_slot: 8` only (see BROKEN CHECK) |

Build CHECK: `bash $HOME/Projects/IW4x-32/tools-re/build_iw4x_fork.sh . Release` -> rc 0.
New tool: `iw4x32/tools/mapchange_rejoin.py` - the 12-minute version of the scenario, PASS/FAIL, shares the
GPU box's test lock with `tools-re/aiboi_test.py`.

## 5. Still open

- Get a probe-free reproduction of the field failure (longer runs, several real clients, or the reporter's box),
  then redo the A/B. Until then the fix is mechanism-justified, not symptom-verified.
- The server console still prints `Error: Unable to set last round results for client num: N` for every slot
  >= 18 at match end - the same 18-wide session layer, server side. Noise today; silencing it like the five
  session hooks do would be a clean follow-up.
- A slot >= 18 client still has no session layer at all (no party, no session-host-backed stats/titles). This
  fix stops that from kicking the player out; it cannot give those clients session features, which the
  closed-source 18-wide arrays make impossible.
- `aiboi_test.py` (outside this worktree): only require `client_slot >= 18` when `--bots >= 18`, and give the
  map-change case a longer window.

NEXT ROUND: hunt a probe-free reproduction of the walk-out (start from `iw4x32/tools/mapchange_rejoin.py`,
28 bots, `--rotate-at 2`, and push `--minutes` to 20 or add a second client), then re-run the A/B against it;
run the two CHECK commands - the `--bots 28` form is the one that can pass.

---

# Previous rounds (1-3)
Task: `iw4x32/tasks/map_change_rejoin.md`. Branch `fix/iw4x32-map-change`. Round 1.

## 0. Plan / state

- Reproduce with the live test (`--bots 8 --client --minutes 5 --map-change-at 2`), read the **client** console
  (the test only prints the server's) before changing code.
- The CHECK commands are the build and the live test; both exist, so the deliverable is in place from the start.
- Client console capture: the test script lives outside this worktree and the round rules forbid editing files
  outside it, so the diagnosis runs use a scratch copy of it (`.scratch/aiboi_cli.py`) that does the same thing
  plus dumps the client's `main/console_mp.log` and greps the server log for the IW4x-32 reject line. The CHECK
  command itself is run unchanged.

## 1. Evidence from the live test (baseline build, unmodified code)

Run A - the CHECK form `--bots 8 --client --map-change-at 2` (scratch runner, 10 s polls):

* 8 bots + the client: the client lands in **slot 8**, not >= 18, because the test spawns the bots first and the
  client takes the first free slot. The CHECK's pass rule needs `client_slot >= 18`, so with `--bots 8` it can
  never pass whatever the code does - see BROKEN CHECK at the top.
* Nothing crashed, the server stayed up, the client was still in the server after the "map change".

Run B/C - `--bots 28 --client --map-change-at 2` (client in slot 28, `-stdout` so its console is captured):

* Before the change: 29 players, human in slot 28. `rcon map_rotate` -> the client console prints
  `Server changing map mp_rust, gametype dom`, it reloads `mp_rust_load`/`mp_rust` and is back in the game;
  status keeps showing 29 players with the human in slot 28.
* **The server console shows no second level restart at all**: no second `------ Server Initialization ------`,
  no second `iw4x32: 32-slot server - ...` line, no `Client N connecting`, no new
  `Going from CS_FREE to CS_CONNECTED` for the human's guid. The bots are re-created (bot28..bot55 take slots
  0..27) but the human's client slot 28 is never freed and never re-connected.
* Reason: the test server's playlist (`userraw/server.cfg`: `addGametype dom`, `addMap mp_rust`) holds exactly
  one map, so `map_rotate` rotates to the *same* map - the engine does not run `SV_SpawnServer`, nobody gets
  disconnected, and the client only reloads the map locally. The live report's rotation (`ShutdownGame`, then
  `Server Initialization`, then our `iw4x32: 32-slot server` line) is a real level change through
  `SV_SpawnServer`, which drops every client. So the CHECK's `--map-change-at` step does not reproduce the bug.

Next: force a real level change (`rcon map mp_broadcast`) and read both consoles.

### What the code does today (client side, map change)

- `iw4x.dll` registers the `iw4x32` userinfo dvar from the `CL_Init` hook (`_e32_cl_init_hook`, 0x4D9571) - once
  per process, not per connect.
- `CG_ParseServerinfo` hook (`_e32_cg_si_hook`, 0x4CCF44) reads `sv_iw4x32` and calls `SetLayout()`; `SetLayout`
  returns early when the layout is already what is asked for, so a reconnect re-parsing serverinfo is a no-op.
- `SV_DirectConnect` hook (`_e32_dc_check`) rejects any remote client whose userinfo lacks `iw4x32\1`, printing
  `rejected connect: client without the iw4x32 (32-player) build` in the server console.
- IW4x itself follows a server map change through `Maps::RotateCheckStub` (hook at 0x5AA91C): if the new map is
  installed and hashed OK it calls the engine's rotate-map routine (0x487C50) on the client, otherwise it
  disconnects and re-`reconnect`s through the IW4x container/party path.

## 2. What actually reproduces: the client leaves on its own, `@XBOXLIVE_PARTYENDED`

The live report's client console (`userraw/console_mp.log` from the v2.0 test box) ends with

```
[    665018] Disconnecting from 00000000.000000000000:0 (@XBOXLIVE_PARTYENDED) at time 665018
```

- nothing before it, no error, no crash dump - the client walks out of the game by itself and goes back to the
  menu (`CL_Live_StartPrivateParty` right after). From the server's side the client then goes quiet and is
  dropped `GAME_DROPPEDFORINACTIVITY`, which is what the server log shows.
- the host address is `00000000.000000000000:0`: the client's own party has no host address recorded.

Reproduced with our own runner (`.scratch/live_repro.py`: stock `iw4x.exe` + this branch's `iw4x.dll`, 32 slots,
`+map_rotate`, 28 bots, one human, `-stdout` on both):

| run | bots | human slot | scorelimit | level restart | result |
|---|---|---|---|---|---|
| live1 | 28 | 28 | 200 | none seen | `@XBOXLIVE_PARTYENDED` at client time **479 s** |
| live2 | 28 | 28 | 200 | `map_restart` at 2 min | `@XBOXLIVE_PARTYENDED` at **427 s** |
| expE  | 28 | 28 | 999999 | none | **clean at 643 s** |
| expF  | 28 | 28 | 200 | none | `@XBOXLIVE_PARTYENDED` at **720 s** |
| expA  | 8  | **0**  | 200 | none | **clean at 714 s** |

So the trigger is **the human sitting in a slot >= 18**, not the map change: with 8 bots the human is in slot 0
and survives 12 minutes, with 28 bots the human is in slot 28 and walks out after 7-12 minutes (the time
varies; a level restart seems to bring it sooner). The map change in the live report is when the box *noticed*
the client was gone.

Why: the stock engine sizes the XLive session/party layer for 18 (`ClientInfo users[18]` at `sessionState+0x230`,
`RegisteredUser internalRegisteredUsers[18]`, `PartyMember partyMembers[18]` at `party+0x1D8`, and the member
loops are hard-bounded `i < 0x12`). IW4x-32 does not enlarge those - it keeps slots >= 18 out of them with five
hooks (`SV_UserinfoChanged` 0x401AAD, `SV_DropClient` 0x4C17DC, `Session_GetXuidForSlot` 0x487C10,
`Session_SetClientAddress` 0x49ABB0, PartyHost member teardown 0x4D3D00).

### The probe (temporary hook, `iw4x32-probe` file next to `iw4x.exe`)

Hooking the party host-timeout handler (0x5028B0), the "party host gone" helper (0x4A7CA0) and the
disconnect-reason handler (0x4B6010) gives the exact chain, every time:

```
iw4x32-probe: disconnect reason '<the reason the server sent>'
iw4x32-probe: party-gone  from 004B60FC syslink 1 f1848 0 f0C 0 sessIdx 0 f18 0 adr 0 0.0.0.0:0
iw4x32-probe: party-timeout from 004A7CE4 ...
Disconnecting from 00000000.000000000000:0 (@XBOXLIVE_PARTYENDED) at time 611469
```

- `0x4B60FC` is the `call 0x4A7CA0` inside the engine's **disconnect-reason handler** (`0x4B6010`): it knows
  `EXE_MATCHENDED`, `EXE_SERVERQUIT`, `EXE_MIGRATIONABORTED`, `EXE_MIGRATION_IN_PROGRESS`, `hostquit`,
  `EXE_PLAYERKICKED`, `roundsdone`, `XBOXLIVE_SIGNINCHANGED` - **anything else falls through to the party-gone
  path**, which ends the game with `@XBOXLIVE_PARTYENDED`.
- `syslink 1`: the `systemlink` dvar is on, so `0x5028B0` takes its first branch and drops without printing
  anything - that is why the client log shows no reason at all.
- **Caveat found the hard way**: in the runs above the reason was the test's own `rcon quit` at the end of the
  run. The `@XBOXLIVE_PARTYENDED` in the table above is that artifact, not the live failure. The live client
  left the same way (through 0x4B6010) while its server was still up, so what matters is *which reason string*
  the server sends - the probe now prints it.

---

# Previous round report — IW4x-32 engine component

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

---

# Round 2 - the walk-out: `@XBOXLIVE_PARTYENDED` on a 32-slot server

## BROKEN CHECK

```
python3 $HOME/Projects/IW4x-32/tools-re/aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll --bots 8 --client --minutes 5 --map-change-at 2
```

The pass rule in `aiboi_test.py` is

```python
ok = alive_all and new_dumps == 0 and best >= want and (not a.client or top >= 18) and \
     (a.map_change_at is None or (changed and after >= want))
```

`top >= 18` is the client's slot, and the test spawns the bots **before** the client, so with `--bots 8` the
client always lands in slot 8. `top >= 18` can never be true, so the CHECK fails no matter what the code does.
The working form is `--bots 28` (client in slot 28, i.e. outside the stock 18-player session layer, which is
exactly the case the bug is about):

```
python3 $HOME/Projects/IW4x-32/tools-re/aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll --bots 28 --client --minutes 5 --map-change-at 2
```

That form passes (client in slot 28 before and after the change, no minidumps) - but it passes on the *unfixed*
build too, because the test server's playlist holds one map and 5 minutes is shorter than a 28-bot match. See
"what actually reproduces" below.

## What actually reproduces

Two live runs of the scratch runner (`--bots 28`, human in slot 28, no forced change) died on their own:

| run | what the client did |
|---|---|
| `t1791883557` (live1) | played fine, then at client time 479 s: `Disconnecting from 00000000.000000000000:0 (@XBOXLIVE_PARTYENDED)`. The server log ends in the middle of a level restart (`MapRotation: applying key 'map' ...`, `Getting bots...`) - the match had ended and the server was rotating. |
| `t1791884097` (live2) | forced map change at 163 s, client reloaded and was back in the game at 177 s, then died at 427 s with the same `@XBOXLIVE_PARTYENDED`, with no server-side event at that time. |

So the report "the client does not come back after a map change" is a **walk-out**: the client does come back,
plays, and is then thrown out to the lobby by the party/session layer. It is not the map change itself, it is
whatever happens later to a client that sits outside the 18-wide session layer.

## The chain, with probes

Probe hooks (enabled by an `iw4x32-probe` file next to `iw4x.exe`, diagnostic only) on the party-gone helper
(0x4A7CA0), the disconnect-reason handler (0x4B6010), the end-game pending processor (0x4BAA69), `SV_EndGame`
(0x4CA1E0), the end-game flag setter with no reason (0x474050), the end-game disconnect broadcast (0x6260A0) and
the per-client disconnect sender (0x407C80).

Run `t1791896953` (D4: 28 bots, 13 min, default `scr_dom_scorelimit 200`) walked out at 795 s:

```
server:  Error: Unable to set last round results for client num: 21 .. 28     <- session layer does not know slots >= 18
         Rotating map...  /  CL_Disconnect called for local client 0  /  ==== ShutdownGame (1) ====  /  Server Initialization
client:  Server changing map mp_rust, gametype dom
         ... full reload, back in the game ("Playing smoke grenades at time 806800") ...
client:  iw4x32-probe: disconnect reason 'EXE_SERVERKILLED'
         iw4x32-probe: party-gone   from 004B60FC syslink 1 ...
         iw4x32-probe: party-timeout from 004A7CE4 syslink 1 ...
         Disconnecting from 00000000.000000000000:0 (@XBOXLIVE_PARTYENDED) at time 794793
```

Engine reading (stock exe, Ghidra):

* `0x6260A0` broadcasts `disconnect <reason>` to every client, and it is reached only through
  `0x4F5BC0` <- `0x4806C0` <- `0x4BAA60`, the "end game pending" processor. `0x4BAA60` takes the reason from
  the global at `0x20987A8` and **falls back to `EXE_SERVERKILLED` when that global is empty**. The reason is
  written by `SV_EndGame` (`0x4CA1E0` -> `0x627500`, which sets `roundsdone` / `EXE_MIGRATIONLIMIT` /
  `hostquit` / `EXE_MATCHENDED`); the level restart wipes the global, so a pending end game processed after the
  restart broadcasts `EXE_SERVERKILLED`. Whether the client sees it at all is a race - run
  `t1791899598` (D5) ended the match with `iw4x32-probe: sv-endgame from 005F7DA2` (the `exit_level` thunk) and
  the pending processor never ran, so nothing was broadcast and nobody walked out.
* `0x4B6010` is the client's disconnect-reason handler. It knows `EXE_MATCHENDED`, `EXE_SERVERQUIT`,
  `EXE_MIGRATIONABORTED`, `EXE_MIGRATION_IN_PROGRESS`, `EXE_PLAYERKICKED*`, `hostquit`, `roundsdone`,
  `XBOXLIVE_SIGNINCHANGED`. `hostquit` and `roundsdone` - the two ways a match ends on a server that stays up -
  it simply **ignores**. Anything else, `EXE_SERVERKILLED` included, goes through the party-gone helper
  `0x4A7CA0` and then `Com_Error(2, ...)`, which leaves the game.
* `0x4A7CA0` and all 12 party/session state-machine paths funnel into `0x5028B0`. For a systemlink client
  (`systemlink` dvar, dvar block `0x649E714`) that handler does exactly one thing: `0x40FF00(cl, lcn,
  "@XBOXLIVE_PARTYENDED", 1)` - tear the session down, open `menu_xboxlive_lobbyended` / `findgame`, and leave
  the game. There is no migration attempt on LAN.
* The other way into `0x5028B0` is the keepalive check `0x4973A0`: "Host has timed out. Disconnecting from %s
  host" after 12 s without hearing from the party/lobby host. That is the path live2 most likely took - a slot
  >= 18 client is never registered with the session host, so the session host never answers it. Those messages
  are on the `network` channel, which IW4x hides by default, which is why they never showed in a log.

## The fix

Both paths end in the same two engine functions, so both are handled there, in `src/Components/Modules/IW4x32.cpp`:

1. **`0x5028B0` (party host timeout) - `PartyTimeout_Stub` / `PartyTimeoutSkip`.** Skip the handler when the
   `systemlink` dvar is set *and* the client's connection state is `CA_CONNECTED` or above. A LAN client that is
   still connected to the game is not in a party that can time out; if the server really goes away the engine's
   own UDP path still fires (`0x5A8DF0`, "Server timed out ... `EXE_SERVER_TIMEOUT`"). Callers that were in the
   middle of a state machine just continue - `0x4973A0` carries on with its per-frame work after the call.
2. **`0x4B6010` (disconnect reason) - `DisconnectReason_Stub` / `DisconnectReasonSkip`.** Ignore
   `EXE_SERVERKILLED` for a systemlink client that is in the game, the way the handler already ignores
   `hostquit` and `roundsdone`. Without this, skipping only the party timeout still leaves the handler's
   `Com_Error(2, ...)` to throw the client out.

Both guards require the `systemlink` dvar, so a signed-in/online client keeps the stock behaviour.

## Test evidence

