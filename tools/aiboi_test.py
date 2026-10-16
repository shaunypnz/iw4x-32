#!/usr/bin/env python3
"""aiboi_test.py — run a live IW4x game test on the GPU box (site config "gpu_ssh") with a given iw4x.dll.

    aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll [--bots 28] [--client] [--minutes 5] [--map mp_rust]
                  [--map-change-at MIN] [--case baseline,rejoin]
    aiboi_test.py --self-test        # no box, no game: judge the recorded transcripts against the same checks

What the live run does (one test at a time on the box - a lock file there; a second caller waits):
  1. copies the DLL into a throwaway game folder on the box (hard-link copy of the test game folder, the STOCK
     iw4x.exe, so only the DLL under test differs)
  2. starts a 32-slot LAN dedicated server under Wine (its own Wine prefixes: the live test game and anything
     else on the box are never touched), adds --bots bots over rcon
  3. --client: also starts a game client on the box's desktop, rendered by the box's own GPU, joins iw4x://
  4. --map-change-at MIN: forces a map change mid-test. --change-via rotate (default) goes the way a real match
     does at its end: the copy's server.cfg names the next map in sv_maprotation (the engine snapshots the
     rotation when the level starts, so it has to be there before +map) and the test fires rcon map_rotate -
     twice, because the first map_rotate after a manual +map only restarts the current map. --change-via map
     fires rcon map <map2> directly. Either way the bots are re-added afterwards.
  5. watches for --minutes: player count, highest slot in use, server alive, client process up, new crash dumps
  6. stops everything it started (by PID), removes the folder, prints a report and exits 0 = pass

Test cases (--case, default: baseline, plus rejoin when --client and --map-change-at are both given). Every case
judges one observation record - what the run saw - and prints one line per check:
  baseline  server alive the whole run, no new crash dump, every bot in, and with --client the client holds a
            slot >= 18 (only the 32-player engine changes can put a client that high).
  rejoin    what actually happened to the client across a forced map change, read off the two console logs and
            the status polls: it got the server's map-change notice, it came back on its own (in how long), it
            finished loading the new level (game state + cgame init in its own console, or - when neither copy of
            that console has flushed that far - a live usercmd stream on the server), it logged no
            session-ending error, its process is up, and the bots are back. The way back is asserted as a chain,
            not as an end state (`client_reinit_sequence`): notice -> the new level's fastfile -> game state
            taken -> the fork's 32-player layout re-applied on the new connect -> cgame init done -> the server
            handing the human guid a slot again after its level restart -> in the level; the first step that is
            missing, or stamped out of order, is named. The slot it had before and after is
            reported next to all of this and judged by its own check (high-slot coverage) - a client sitting in
            a low slot is a layout gap, it is not a failed rejoin. This is the case for the "client does not come
            back after a map change" bug, and the last line it prints names the FIRST thing that went wrong in
            plain words ("client did not reconnect within 150 s after the map change") with the slots as context.

The console logs are the evidence: `status` only says whether a name is on the server, not what the client did
about the change. Both game processes log into the same userraw/console_mp.log* set (the client rotates it when
it starts, so the server's lines land in .000), and each block begins with the command line that process was
started with - that is what tells the client's lines from the server's. The engine stamps every console line
with milliseconds since that process started and the file is append-only, so the lines are in event order and
the reload timings come out of the client's own clock.

A console file is not the console: the game writes it through a 4 KB stdio buffer and flushes it only when that
buffer is full, so the last lines of a level reload sit in the process (box-checked - the client's log sat at
108730 bytes for two minutes while the client kept printing, and the missing 'CL_InitCGame' line appeared when a
`say` flood pushed the buffer out). So the run reads two copies of the client's console (its console log and its
-stdout copy), makes the client print before fetching, and keeps the server's `lastmsg` for that client as a
second, independent witness that it is in the level: a client on a loading screen sends no usercmds.

--self-test runs the cases over the recorded transcripts at the bottom of this file: the good one must pass, and
every bad one must fail the check that names its problem - a probe that always reads "perfect" is broken."""
import argparse, json, os, re, subprocess, sys, time

CLIENT_NAME = "live-test"                 # the test client joins with +set name <CLIENT_NAME>
SLOT_32 = 18                              # a slot >= 18 exists only with the 32-player layout live
REJOIN_MAX_S = 150.0                      # a stock client follows a map change within about a minute
PLAYING_MAX_MS = 2000                     # a client in the level sends a usercmd every frame, so the server's
#                                         `lastmsg` for it stays near 0 (11400 ms once its process was killed)
PLAYING_MIN_S = 30.0                      # ... and only a poll this far after the change can prove it is in it
FLUSH_LINES = 80                          # `say` lines enough to carry the client's 4 KB console buffer to disk
MAP_INIT = "iw4x32: .*slot server"        # the dll's server-init line (printed once per process, not per level)
CLI_LOG = "userraw/console_mp.log"        # console log of whatever game process opens it last (see --save-logs)
CLI_OUT = "client.log"                    # the client's -stdout copy of the same console, without the ms stamps
CLI_FOLLOW = "Server changing map"        # the client got the server's map-change notice and reloads with it

# the console lines that tell the rejoin story, as a grep -E pattern (the box filters them out of the ~100 KB
# logs, so only a few hundred lines cross the wire) and as the same set of substrings for the recorded transcripts
CLI_EVENT = (r"iw4x://|-dedicated|Server changing map|Setting state to CA_|CL_InitCGame|CL_Disconnect|Disconnecting"
             r"|Server disconnected|Connection lost|Com_Error|Sys_Error|Exception|Modifying session|Loading fastfile"
             r"|Unloaded fastfile|newSnap|Error:|Adding channel: error|Going from CS_|Client [0-9]+ connecting"
             r"|challenge ping|Server Initialization|iw4x32: |IW4x32: |timed out")


# ---------------------------------------------------------------- the judging half (no box, no game)

def chk(name, ok, detail, reason=""):
    """one check: `detail` is what was measured, `reason` the plain words the verdict line uses when it failed."""
    return {"name": name, "ok": bool(ok), "detail": detail, "reason": reason}


ROW = re.compile(r"^\s*(\d+)\s+(-?\d+)\s+(-?\d+)\s+(\S+)\s+(.*)$")
STAMP = re.compile(r"^\[\s*(\d+)\]\s?(.*)$")


def parse_status(text):
    """rcon `status` -> (map or None, [(slot, guid, name, lastmsg_ms or None), ...]). Bots carry a bot<N> guid;
    the header, the ---- line and the map line do not match ROW, so they drop out. Colour codes are stripped from
    the name, and `lastmsg` is read off the right end of the row (the name column is not a fixed width - IW4x
    appends " iw4x" to every name, so counting from the left would land on the wrong column)."""
    m = re.search(r"^\s*map:\s*(\S+)", text, re.M)
    rows = []
    for l in text.splitlines():
        g = ROW.match(l)
        if not g:
            continue
        rest = [re.sub(r"\^\d", "", t) for t in g.group(5).split()]
        lastmsg = int(rest[-4]) if len(rest) >= 4 and rest[-4].lstrip("-").isdigit() else None
        rows.append((int(g.group(1)), g.group(4), rest[0] if rest else "", lastmsg))
    return (m.group(1) if m else None), rows


def humans(rows):
    return [r for r in rows if not r[1].lower().startswith("bot")]


def bot_guids(rows):
    return {r[1].lower() for r in rows if r[1].lower().startswith("bot")}


def client_slot(rows):
    """slot of our test client in a status row list, None when it is not on the server."""
    for slot, _guid, name, _lastmsg in humans(rows):
        if name.lower() == CLIENT_NAME:
            return slot
    return None


def client_lastmsg(rows):
    """ms since the server last heard from our test client, None when it is not on the server. This is the
    server's own witness that the client finished loading: in the level it sends a usercmd every frame (0-12 ms
    on the box), on a loading screen or dead it sends nothing (11400 ms and climbing after its process was
    killed)."""
    for _slot, _guid, name, lastmsg in humans(rows):
        if name.lower() == CLIENT_NAME:
            return lastmsg
    return None


# ------------------------------------------------- the console logs: what the client did about the change

CLI_NOTICE = re.compile(r"^Server changing map (\w+)")   # the engine writes "map mp_crash, gametype dom"
CLI_LOADED = re.compile(r"^CL_InitCGame:\s+([\d.]+) seconds")
CLI_REINIT = "Setting state to CA_LOADING in CL_InitCGame"   # the client is taking the new level's game state
CLI_LAYOUT = "iw4x32: server is"    # the client re-read sv_iw4x32 on the new connect and re-applied the layout
CLI_FASTFILE = re.compile(r"^Loading fastfile (\w+)$")        # the new level's data reached the client
CLI_ORDER = ("notice", "fastfile", "reinit", "loaded")       # the client steps whose ms stamps must be ordered
CLI_DROP = re.compile(r"Disconnecting from |Disconnecting: |Server disconnected|Connection lost|CL_Disconnect"
                      r"|Com_Error|Sys_Error|Exception|timed out")
CLI_WHY = re.compile(r"\(@([A-Z_]+)\)")
CLI_FATAL = re.compile(r"Disconnecting from |Server disconnected|Connection lost|Com_Error|Sys_Error|Exception")
SV_SLOT = re.compile(r"Going from (\w+) to (\w+) for (.*?) \(num (\d+) guid \"(\w+)\"\)")


def console_events(text):
    """console text -> [(ms, line), ...]. The engine stamps every line with ms since that process started and
    writes the file append-only, so the list is in event order; un-stamped lines belong to the one above."""
    out, ms = [], 0
    for l in (text or "").splitlines():
        g = STAMP.match(l)
        if g:
            ms, l = int(g.group(1)), g.group(2)
        elif not l.strip():
            continue
        if l.strip():
            out.append((ms, l))
    return out


def client_story(text, map_to):
    """the client's own console lines around the forced map change: did it get the notice, did it leave the
    session, did it take the new level's game state, did it finish loading it, and what did it error about.
    Everything is measured off the last notice for `map_to` (the rotate path restarts the current map first)."""
    ev = console_events(text)
    notices = [(i, ms, CLI_NOTICE.match(line).group(1)) for i, (ms, line) in enumerate(ev) if CLI_NOTICE.match(line)]
    at = next((n for n in reversed(notices) if n[2] == map_to), notices[-1] if notices else None)
    tail = ev[at[0] + 1:] if at else []
    drop = [(ms, line) for ms, line in tail if CLI_DROP.search(line)]
    fatal = [(ms, line) for ms, line in drop if CLI_FATAL.search(line)]
    benign = [(ms, line) for ms, line in tail if re.search(r"Error:|Adding channel: error", line)
              and not CLI_FATAL.search(line)]
    reinit = next((ms for ms, line in tail if CLI_REINIT in line), None)
    fastfile = next((ms for ms, line in tail if (g := CLI_FASTFILE.match(line)) and g.group(1) == map_to), None)
    layout = next((ms for ms, line in tail if CLI_LAYOUT in line), None)
    done = next(((ms, float(CLI_LOADED.match(line).group(1))) for ms, line in tail if CLI_LOADED.match(line)), None)
    # a copy without the engine's ms stamps (the -stdout one) still proves a line was printed, but every one of
    # its lines would read as ms 0: keep the order, drop the timings rather than invent them
    stamped = any(STAMP.match(l) for l in (text or "").splitlines())
    return {"lines": len(ev), "stamped": stamped, "notices": [n[2] for n in notices],
            "notice": None if at is None else {"ms": at[1], "map": at[2]},
            "dropped": drop, "fatal": fatal, "benign": benign,
            "reinit_ms": reinit if stamped else None, "reinit": reinit is not None,
            "fastfile_ms": fastfile if stamped else None, "fastfile": fastfile is not None,
            "layout_ms": layout if stamped else None, "layout": layout is not None,
            "loaded_ms": done[0] if (done and stamped) else None,
            "loaded": done is not None, "load_secs": done[1] if done else None,
            "since_notice": lambda ms: None if at is None or ms is None or not stamped else (ms - at[1]) / 1000.0,
            "last": ev[-1][1] if ev else ""}


def client_story_all(texts, map_to):
    """the rejoin story out of every copy of the client's console the run left behind (its console log and, with
    -stdout, its stdout copy). Each copy is written through the game's own 4 KB buffer and lags the process by
    whatever it has not flushed, so a line missing from one copy is not evidence of anything: the story is what
    the copies say together. The timings come from whichever copy carries the engine's ms stamps."""
    stories = [client_story(t, map_to) for t in texts if t and t.strip()]
    if not stories:
        return dict(client_story("", map_to), copies=0, timed=False)
    ref = max(stories, key=lambda s: (s["loaded"], s["reinit_ms"] is not None, s["notice"] is not None))
    out = dict(ref, copies=len(stories), timed=ref["stamped"], lines=sum(s["lines"] for s in stories),
               notices=sorted({m for s in stories for m in s["notices"]}))
    for key in ("dropped", "fatal", "benign"):
        seen, merged = set(), []
        for s in stories:
            for ms, line in s[key]:
                if line not in seen:
                    seen.add(line)
                    merged.append((ms, line))
        out[key] = sorted(merged, key=lambda e: e[0])
    # a re-init step counts when any copy printed it (each copy lags the process by whatever it has not
    # flushed), and its offset comes from whichever copy carries the engine's ms stamps next to it
    for key in ("fastfile", "reinit", "layout", "loaded"):
        out[key] = any(s[key] for s in stories)
    for key in ("fastfile_ms", "reinit_ms", "layout_ms", "loaded_ms"):
        if out[key] is None:
            out[key] = next((s[key] for s in stories if s[key] is not None), None)
    return out


def server_story(text):
    """the server's console lines: level restarts, and every slot the non-bot (human) guid was given or took
    back - `Going from CS_FREE to CS_CONNECTED for  (num 28 guid "<human>")` is the server handing out a slot.
    `handshake` is the slot the server handed the human guid AFTER its last level restart: the restart drops
    everyone, so a client that came back through that line re-connected, and one that only still shows up in a
    later `status` poll did not necessarily."""
    ev = console_events(text)
    restart_ms, slots, drops, connects, ping_ms = None, [], [], 0, None
    for ms, line in ev:
        if "Server Initialization" in line:
            restart_ms = ms
        if "challenge ping from" in line and "connecting" in line:
            connects += 1
            ping_ms = ms
        g = SV_SLOT.search(line)
        if not g or g.group(5).lower().startswith("bot"):
            continue
        (drops if g.group(2) != "CS_CONNECTED" else slots).append((ms, int(g.group(4)), g.group(5), g.group(2)))
    again = [e for e in slots if restart_ms is not None and e[0] > restart_ms]
    handshake = None if not again else {"ms": again[0][0], "slot": again[0][1], "guid": again[0][2],
                                        "ping_ms": ping_ms if (ping_ms is not None and ping_ms > restart_ms)
                                        else None}
    return {"lines": len(ev), "restarts": sum(1 for ms, line in ev if "Server Initialization" in line),
            "connects": connects, "restart_ms": restart_ms, "handshake": handshake,
            "human_slots": [s for s in slots], "human_drops": drops}


def reinit_sequence(cli, srv, playing, map_to):
    """the client's re-initialization / re-connection chain after the map change, step by step, in the order the
    engine runs it - not just the state at the end of it. The client's steps come off its own console tail (the
    last notice for `map_to`), the last two off the server's console: the level restart drops every client, so
    the client has to come back through the connect handshake and be in the level to send anything. The server's
    lines are only placed after its own restart - the two processes have separate clocks, so their ms are never
    compared. The last client step counts as done on its cgame init line or, when neither console copy flushed
    that far, on the usercmds the server gets from it. Returns (steps, gap): steps is [(name, ok, ms, note), ...]
    in the order they must happen, gap the first step that is missing or out of order (None when the whole chain
    is there)."""
    steps = []

    def add(name, ok, ms, note):
        steps.append((name, bool(ok), ms, note))

    add("notice", cli["notice"] is not None, None if cli["notice"] is None else cli["notice"]["ms"],
        f"no '{CLI_FOLLOW} {map_to}' line in its console")
    add("fastfile", cli["fastfile"], cli["fastfile_ms"], f"no 'Loading fastfile {map_to}' line after the notice")
    add("reinit", cli["reinit"], cli["reinit_ms"], f"no '{CLI_REINIT}' line after the notice")
    add("layout", cli["layout"], cli["layout_ms"],
        f"no '{CLI_LAYOUT} ...' line after the notice - it never re-read the server's layout on the new connect")
    add("loaded", cli["loaded"] or playing, cli["loaded_ms"],
        "no 'CL_InitCGame: N seconds' line after the notice and no usercmd reaching the server - it never got "
        "into the level")
    add("server_reconnect", srv["handshake"] is not None, srv["handshake"]["ms"] if srv["handshake"] else None,
        "the server never handed the human guid a slot again after its level restart")

    gap = next((s for s in steps if not s[1]), None)
    if gap is None:
        # all there - the stamped client steps must also sit in the order the engine runs them (the layout line
        # prints inside the reload window, 1 ms either side of the game-state line, so it is not ordered here).
        # A step stamped before the one that must precede it belongs to the first join, not to the rejoin.
        timed = [(n, ms) for n, _ok, ms, _note in steps if n in CLI_ORDER and ms is not None]
        for n, ms in timed:
            early = next((e for e in timed if CLI_ORDER.index(e[0]) < CLI_ORDER.index(n) and ms <= e[1]), None)
            if early:
                gap = next(s for s in steps if s[0] == n)[:2] + (ms, f"its own console stamps it at {ms} ms, "
                                                                 f"before '{early[0]}' at {early[1]} ms - those "
                                                                 "lines belong to the first join, not the rejoin")
                break
    return steps, gap


def rejoin_facts(o):
    """one dict with everything the rejoin case judges: the polls say where the client sat and whether the server
    still hears from it, its own consoles say what it did about the change. Computed once so the checks and the
    verdict line cannot disagree."""
    before = [p for p in o["polls"] if p["t"] <= o["map_change_t"]]
    after = [p for p in o["polls"] if p["t"] > o["map_change_t"]]
    cli = client_story_all([o.get("client_log"), o.get("client_stdout")], o["map_to"])
    srv = server_story(o.get("server_log"))
    back = [p for p in after if client_slot(p["rows"]) is not None]
    slot_after = client_slot(back[-1]["rows"]) if back else None
    live = [(p["t"], client_lastmsg(p["rows"])) for p in back if client_lastmsg(p["rows"]) is not None]
    lastmsg = live[-1][1] if live else None
    playing_s = live[-1][0] - o["map_change_t"] if live else None
    playing = lastmsg is not None and lastmsg <= PLAYING_MAX_MS and playing_s >= PLAYING_MIN_S
    return {"before": before, "after": after, "cli": cli, "srv": srv,
            "slot_before": client_slot(before[-1]["rows"]) if before else None, "slot_after": slot_after,
            "reconnected": bool(back), "reconnect_s": back[0]["t"] - o["map_change_t"] if back else None,
            "reinit_s": cli["since_notice"](cli["reinit_ms"]), "load_s": cli["since_notice"](cli["loaded_ms"]),
            "loaded_console": cli["loaded"], "lastmsg": lastmsg, "playing_s": playing_s, "playing": playing,
            "loaded": cli["loaded"] or playing,
            "disconnected": bool(cli["dropped"]), "fatal": cli["fatal"], "benign": cli["benign"],
            "seq": reinit_sequence(cli, srv, playing, o["map_to"])}


def secs(v):
    """a duration in words, for the case where the copy of the console that proves the load carries no stamps."""
    return "an unmeasured time" if v is None else f"{v:.0f} s"


def copies(n):
    return f"{n} copy" if n == 1 else f"{n} copies"


def copies_read(cli):
    """how much of the client's console the run actually got hold of, in words."""
    return "no copy of its console" if not cli["copies"] else f"{copies(cli['copies'])} of its console"


def slot_context(f):
    hi = "met" if (f["slot_after"] or 0) >= SLOT_32 else "not met"
    return (f"slots: {f['slot_before']} before the change, {f['slot_after']} after "
            f"(high-slot coverage >= {SLOT_32}: {hi})")


def case_baseline(o):
    best = max((len(p["rows"]) for p in o["polls"]), default=0)
    top = max([s for p in o["polls"] for s, _g, _n, _l in humans(p["rows"])], default=-1)
    yield chk("server_alive", o["server_alive"], "every status poll answered", "the server stopped answering status")
    yield chk("no_new_crash_dumps", o["new_crash_dumps"] == 0, f"{o['new_crash_dumps']} new minidump(s)",
              f"{o['new_crash_dumps']} new crash dump(s) appeared during the run")
    yield chk("players_in", best >= o["want"], f"most {best} of {o['want']} wanted",
              f"only {best} of {o['want']} players ever got on the server")
    if o["client"]:
        yield chk("client_high_slot", top >= SLOT_32, f"highest human slot {top}, needs >= {SLOT_32}",
                  f"the client never held a slot >= {SLOT_32} - the 32-player layout is not in effect")


def case_rejoin(o):
    """the client must follow the forced map change on its own. The checks are in the order the story happens,
    so the first failure names what actually went wrong; the slot number is judged on its own, last."""
    if not o["client"] or o["map_change_t"] is None:
        yield chk("rejoin_setup", False, "the rejoin case needs --client and --map-change-at",
                  "the rejoin case cannot be judged without --client and --map-change-at")
        return
    f = rejoin_facts(o)
    cli, srv = f["cli"], f["srv"]
    maps = [p["map"] for p in o["polls"] if p["map"]]
    # a level restart drops every client, and IW4x gives each spawnBot the next guid in the session - so the bots
    # that answer after the change are not the bots that answered before it. That is what proves the session
    # really restarted: without it a client that never left would "rejoin".
    gone = bot_guids(f["before"][-1]["rows"]) if f["before"] else set()
    new = set().union(*[bot_guids(p["rows"]) for p in f["after"]]) if f["after"] else set()

    yield chk("client_in_before", any(client_slot(p["rows"]) is not None for p in f["before"]),
              f"{CLIENT_NAME} in status before the change (slot {f['slot_before']})",
              f"{CLIENT_NAME} was not on the server before the map change")
    yield chk("map_changed", len(set(maps)) >= 2, f"maps in status: {maps[0] if maps else '?'} -> "
                                                 f"{maps[-1] if maps else '?'}",
              "the server never changed map - the change command did not reach it")
    yield chk("session_restarted", bool(gone) and bool(new) and not (gone & new),
              f"bot guids before {sorted(gone)[:2]}..{len(gone)} vs after {sorted(new)[:2]}..{len(new)} - "
              "a level restart drops every client, so none may be shared",
              "the session never restarted - nobody was dropped, so nothing had to be rejoined")
    yield chk("client_followed_change", cli["notice"] is not None,
              f"{len(cli['notices'])} '{CLI_FOLLOW}' line(s) in the client console"
              + (f", last one for {cli['notice']['map']}" if cli["notice"] else "")
              + ("" if cli["lines"] else f" - and no client console log at all ({CLI_LOG}*)"),
              "the client never logged the server's map change - it did not get the notice"
              + ("" if cli["lines"] else " (no client console log to read: the client process never ran?)"))
    if f["reconnected"]:
        yield chk("client_reconnected", True, f"back in status {f['reconnect_s']:.0f} s after the change "
                                              f"(limit {REJOIN_MAX_S:.0f} s)"
                  + (f"; the server handed the human guid slot {srv['human_slots'][-1][1]} again"
                     if len(srv["human_slots"]) > 1 else ""))
    else:
        # the reason stays one plain sentence; the console line it died on is in the detail above it
        why = next((m.group(1) for ms, line in cli["dropped"] if (m := CLI_WHY.search(line))), None)
        yield chk("client_reconnected", False,
                  f"{CLIENT_NAME} never appeared in status after the change"
                  + (f"; its console left the session with '{cli['dropped'][0][1][:80]}'" if cli["dropped"] else
                     f"; its console's last line is '{cli['last'][:80]}'"),
                  f"client did not reconnect within {REJOIN_MAX_S:.0f} s after the map change"
                  + (f" - it left the session with @{why} and stayed out" if why else
                     (" and stayed out" if cli["dropped"] else "")))
    if f["loaded_console"]:
        yield chk("client_loaded_map", True,
                  f"took the new level's game state {secs(f['reinit_s'])} after the notice and was in "
                  f"{o['map_to']} {secs(f['load_s'])} after it (cgame init {cli['load_secs']:.2f} s)"
                  if f["load_s"] is not None else
                  f"'CL_InitCGame: N seconds' for {o['map_to']} after the notice in {copies_read(cli)} - not in a "
                  "copy that carries the engine's ms stamps next to the notice, so the run cannot time it")
    elif f["playing"]:
        # neither copy of its console has flushed that far - the server is the witness instead, and a client
        # sitting on a loading screen sends nothing at all
        yield chk("client_loaded_map", True,
                  f"in {o['map_to']} by the server's own account: a usercmd {f['lastmsg']} ms before the last "
                  f"poll, {f['playing_s']:.0f} s after the change ("
                  + ("no client console text at all" if not cli["copies"] else
                     f"no cgame init line in {copies_read(cli)} - they lag the process by up to the game's "
                     "4 KB log buffer") + ")")
    else:
        yield chk("client_loaded_map", False,
                  ("no client console text at all" if not cli["copies"] else
                   f"no '{CLI_REINIT}' + 'CL_InitCGame: N seconds' pair after the notice in {copies_read(cli)} "
                   f"(last line '{cli['last'][:60]}')")
                  + (f"; the server last heard from it {f['lastmsg']} ms before the last poll"
                     if f["lastmsg"] is not None else "; it is not on the server in any later poll either"),
                  f"client reconnected but never finished loading {o['map_to']} - no game state and no cgame "
                  "init in its console, and no usercmd reaching the server")
    # the chain itself, not just its endpoints: a client that ends up in status in the right slot without having
    # re-initialized for the new level (or that the server never took back through the connect handshake) is a
    # rejoin that did not happen, whatever the final state looks like
    steps, gap = f["seq"]
    chain = " -> ".join(n + ("(usercmd)" if n == "loaded" and not cli["loaded"] and f["playing"] else "")
                        + ("" if ok else " MISSING") for n, ok, _ms, _note in steps)
    clock = (", ".join(f"{n} {(ms - cli['notice']['ms']) / 1000.0:+.0f} s" for n, ok, ms, _note in steps
                       if ok and ms is not None and n not in ("notice", "server_reconnect"))
             if cli["notice"] else "")
    hand = (f"the server handed slot {srv['handshake']['slot']} back"
            + (" after a challenge ping" if srv["handshake"]["ping_ms"] is not None else "")
            if srv["handshake"] else "no connect for the human guid after the level restart")
    yield chk("client_reinit_sequence", gap is None, chain + (f" | client clock: {clock}" if clock else "")
              + f" | {hand}",
              "" if not gap else f"the client's re-init chain after the map change broke at '{gap[0]}': {gap[3]}")
    yield chk("client_no_session_error", not f["fatal"],
              f"{len(f['fatal'])} session-ending error line(s) after the change"
              + (f": '{f['fatal'][0][1][:80]}'" if f["fatal"] else "")
              + f"; {len(f['benign'])} known-benign error line(s) (voice channels, missing menu files)",
              "" if not f["fatal"] else "the client logged an error after the map change: "
                                         + f["fatal"][0][1][:80])
    yield chk("client_process_up", bool(f["after"]) and f["after"][-1]["client_up"],
              "client process still up at the end", "the client process is gone by the end of the run")
    yield chk("client_high_slot_after", f["slot_after"] is not None and f["slot_after"] >= SLOT_32,
              f"high-slot coverage: slot {f['slot_before']} before the change, {f['slot_after']} after, "
              f"needs >= {SLOT_32} (the client-side 32-player layout survived the reload)",
              f"the client is back but in slot {f['slot_after']}, below {SLOT_32} - the 32-player layout did not "
              "survive the reload (a layout gap, not a reconnect failure)")
    players_after = max((len(p["rows"]) for p in f["after"]), default=0)
    yield chk("players_back_after", players_after >= o["want"], f"most {players_after} of {o['want']} after "
                                                                "the change",
              f"only {players_after} of {o['want']} players were back after the change")


CASES = {"baseline": case_baseline, "rejoin": case_rejoin}


def verdict(cases, o):
    res = [c for name in cases for c in CASES[name](o)]
    return all(c["ok"] for c in res), res


def verdict_line(cases, o, ok, res):
    """the one line a human reads: what happened, or the FIRST thing that went wrong in plain words - with the
    slot numbers as context only, never as the reason."""
    first = next((c for c in res if not c["ok"]), None)
    if o["client"] and o["map_change_t"] is not None and "rejoin" in cases:
        f = rejoin_facts(o)
        if ok:
            how = (f"finished loading it {f['load_s']:.0f} s after the notice" if f["load_s"] is not None else
                   "finished loading it" if f["loaded_console"] else
                   f"is in it - the server gets a usercmd from it every frame ({f['lastmsg']} ms since the last)")
            return (f"PASS - the client followed the change to {o['map_to']}, reconnected after "
                    f"{f['reconnect_s']:.0f} s and {how} | re-init chain: "
                    + " -> ".join(n for n, _ok, _ms, _note in f["seq"][0]) + f" | {slot_context(f)}")
        return f"FAIL - {(first['reason'] or first['detail']) if first else ''} | {slot_context(f)}"
    if ok:
        return "PASS - " + ", ".join(f"{c['name']} ok" for c in res)
    return f"FAIL - {(first['reason'] or first['detail']) if first else ''}"


# ---------------------------------------------------------------- the recorded transcripts (--self-test)

def status_text(mp, entries):
    """entries [(slot, guid, name, lastmsg_ms), ...] -> rcon status text. The address column stays a placeholder:
    no real IPs in the repo, and nothing here reads it."""
    lines = [f"map: {mp}",
             " num score ping guid                             name            lastmsg address               qport rate",
             "--- ----- ---- -------------------------------- --------------- ------- --------------------- ----- -----"]
    for slot, guid, name, lastmsg in entries:
        lines.append(f"{slot:>3} {0:>4} {12:>3} {guid:>32} {name + '^7':<15} {lastmsg:>7} {'0:<LAN-IP>':<21} {0:>4} {25000:>5}")
    return "\n".join(lines)


def table(bots, client_slot_no, guid0=0, lastmsg=0):
    """a status table: bots in slots 0..bots-1 with session guids bot{guid0}.., our client in client_slot_no
    (None = not on the server) answering the server `lastmsg` ms ago. A level restart drops every bot and the
    re-add names the next ones, so a real change shows guid0 = bots after it and guid0 = 0 before it."""
    slots = [i for i in range(bots + 1) if i != client_slot_no][:bots]
    rows = [(s, f"bot{guid0 + i}", "Lunarion", 12) for i, s in enumerate(slots)]
    if client_slot_no is not None:
        rows.append((client_slot_no, "AB12cd34EF567890", CLIENT_NAME, lastmsg))
    return rows


def obs(polls, want, map_change_t=None, map_to="mp_crash", new_crash_dumps=0, server_alive=True, client=True,
        client_log=None, client_stdout=None, server_log=None, iw4x32_marker=1):
    """polls: [(t, status text, client process up)] -> the observation record the cases judge."""
    ps = []
    for t, txt, up in polls:
        mp, rows = parse_status(txt)
        ps.append({"t": t, "map": mp, "rows": rows, "client_up": up})
    return {"polls": ps, "want": want, "client": client, "map_change_t": map_change_t, "map_to": map_to,
            "new_crash_dumps": new_crash_dumps, "server_alive": server_alive, "client_log": client_log,
            "client_stdout": client_stdout, "server_log": server_log, "iw4x32_marker": iw4x32_marker}


def transcript(mp, change_t, client_after, bots=28, up_after=True, bots_after=None, mp_after="mp_crash",
               restarted=True, lastmsg_after=0):
    """a 5-minute run: bots + client in, map change at change_t (lands on mp_after), client_after = the slot the
    client is back in (None = it never came back), bots_after = how many bots the re-add brought back, restarted
    = the level restart dropped everyone (new bot guids), lastmsg_after = how long ago the server last heard from
    the client afterwards (0 = it is playing, tens of seconds = it is connected but says nothing), polls every
    20 s."""
    polls = [(t, status_text(mp, table(bots, bots)), True) for t in (20, 40, 60, 80, 100, 120)]
    after = bots if bots_after is None else bots_after
    guid0 = bots if restarted else 0
    polls += [(t, status_text(mp_after, table(after, client_after, guid0, lastmsg_after)), up_after)
              for t in (140, 160, 200, 240, 280, 300)]
    return polls, change_t


# The client console of a real run (28 bots + client, mp_rust -> mp_crash), trimmed to the lines the rejoin
# judgement reads: the file lists, dvar dumps and fastfile bookkeeping are dropped, the event lines are verbatim.
# `cli_log` rebuilds it around the forced change so a transcript can stop wherever the story stops.
CLI_BOOT = [(1131, "'+set r_fullscreen 0 +set r_mode 1280x720 +set name live-test iw4x://<test_server>:28971'"),
            (1132, "Adding channel: error"),
            (11657, "CL_Disconnect called for local client 0"),
            (11661, "Loading fastfile mp_rust_load"),
            (12897, "Loading fastfile mp_rust"),
            (17889, "Setting state to CA_LOADING in CL_DownloadsComplete"),
            (17892, "Setting state to CA_LOADING in CL_InitCGame"),
            (17894, "Modifying session in CG_ParseServerInfo() to have 32 public and 0 private slots"),
            (17895, "iw4x32: server is 32-slot - using the 32 player/body layout"),
            (21999, 'Error: Could not load menufile "ui_mp/scriptmenus/callvote.menu".'),
            (22782, "CL_InitCGame:  4.89 seconds"),
            (22940, "oldMessageNum is 15, newSnap.messageNum is 47 - not clearing it because they overlap")]


def cli_log(map_to="mp_crash", notice=True, dropped=None, reinit=True, loaded=True, layout=True, t_notice=144405):
    """the client's console across the forced map change: notice = it got the server's line, dropped = the line
    it left the session with (and nothing after it), reinit = it took the new level's game state, layout = it
    re-read the server's layout on the new connect, loaded = it finished the level (cgame init done). Offsets are
    the real run's, in ms on the client's own clock."""
    out = list(CLI_BOOT)
    if notice:
        out.append((t_notice, f"Server changing map {map_to}, gametype dom"))
        out.append((t_notice + 7, f"Loading fastfile {map_to}_load"))
        out.append((t_notice + 416, 'Error: Could not load material "gradient_slow_fadein".'))
        out.append((t_notice + 1259, "Unloaded fastfile mp_rust"))
        out.append((t_notice + 1266, f"Loading fastfile {map_to}"))
    if dropped:
        out.append((t_notice + 3000, dropped))
    else:
        if reinit:
            out.append((t_notice + 11997, "Setting state to CA_LOADING in CL_DownloadsComplete"))
            out.append((t_notice + 11997, "Setting state to CA_LOADING in CL_InitCGame"))
        if layout:
            # the fork prints this on every connect and every level restart, so a rejoin that re-parsed
            # serverinfo says so - and the layout it picked with it
            out.append((t_notice + 11998, "iw4x32: server is 32-slot - using the 32 player/body layout"))
        if loaded:
            out.append((t_notice + 16010, 'Error: Could not load menufile "ui_mp/scriptmenus/kickplayer.menu".'))
            out.append((t_notice + 16417, "CL_InitCGame:  4.42 seconds"))
            out.append((t_notice + 16417, "Com_TouchMemory: 0 msec. Using sum: 1513413627"))
    return "\n".join(f"[{ms:>9}] {line}" for ms, line in out)


def cli_stdout(map_to="mp_crash", **kw):
    """the same console as cli_log(), without the engine's ms stamps - what the client's -stdout copy looks like.
    It is written through a buffer of its own, so it is ahead of the console log exactly when the console log has
    stopped at a level reload."""
    return "\n".join(re.sub(r"^\[\s*\d+\]\s?", "", l) for l in cli_log(map_to, **kw).splitlines() if l.strip())


def srv_log(map_to="mp_crash", restarts=2, human_slot=28, reconnects=True, handshake=True):
    """the server console of the same run: the two level restarts, the bots the re-add named, and the human's
    slot being handed out again after the change (handshake=False = the restart happened but the server never
    took the human guid back: no challenge ping, no slot line for it after the restart)."""
    out = [(1885, "------ Server Initialization ------"),
           (1890, "iw4x32: 32-slot server - 32-player layout, patched clients only")]
    for i in range(28):
        out.append((70000 + i * 500, f'Going from CS_FREE to CS_CONNECTED for  (num {i} guid "bot{i}")'))
    out.append((78927, "Client 0 connecting with 100 challenge ping from 0:<LAN-IP>"))
    out.append((78928, f'Going from CS_FREE to CS_CONNECTED for  (num {human_slot} guid "AB12cd34EF567890")'))
    if restarts > 1:
        out.append((91100, "------ Server Initialization ------"))
        out.append((91105, "iw4x32: 32-slot server - 32-player layout, patched clients only"))
        for i in range(28):
            out.append((259000 + i * 500, f'Going from CS_FREE to CS_CONNECTED for  (num {i} guid "bot{28 + i}")'))
        if reconnects and handshake:
            out.append((262000, "Client 0 connecting with 100 challenge ping from 0:<LAN-IP>"))
            out.append((262001, f'Going from CS_FREE to CS_CONNECTED for  (num {human_slot} guid "AB12cd34EF567890")'))
    return "\n".join(f"[{ms:>9}] {line}" for ms, line in out)


def self_test():
    n, fails = 0, []

    def expect(what, cases, o, want_ok, want_fails=(), want_reason=None, want_ok_checks=()):
        nonlocal n
        n += 1
        ok, res = verdict(cases, o)
        bad_names = {c["name"] for c in res if not c["ok"]}
        line = verdict_line(cases, o, ok, res)
        if ok != want_ok or not set(want_fails) <= bad_names:
            fails.append(f"{what}: got {'PASS' if ok else 'FAIL'} {sorted(bad_names)}, wanted "
                         f"{'PASS' if want_ok else 'FAIL'} with {sorted(want_fails) or 'no failures'}")
        elif want_reason and want_reason not in line:
            fails.append(f"{what}: verdict line '{line}' does not name '{want_reason}'")
        missing = [c for c in want_ok_checks if c not in {x["name"] for x in res if x["ok"]}]
        if missing:
            fails.append(f"{what}: {missing} did not pass, and they should have")

    # the parser sees the real status shape
    mp, rows = parse_status(status_text("mp_rust", table(28, 28)))
    n += 1
    if mp != "mp_rust" or len(rows) != 29 or client_slot(rows) != 28 or len(humans(rows)) != 1:
        fails.append(f"parse_status: map {mp}, {len(rows)} rows, client slot {client_slot(rows)}, "
                     f"{len(humans(rows))} human(s) - wanted mp_rust, 29, 28, 1")

    good, change_t = transcript("mp_rust", 120.0, 28)
    expect("good run", ["baseline", "rejoin"], obs(good, 29, map_change_t=change_t, client_log=cli_log(),
                                                  server_log=srv_log()), True,
           want_reason="reconnected after", want_ok_checks=("client_reinit_sequence",))

    # bad: the client disconnects at the change and never comes back - the verdict must say it did not reconnect
    lost, change_t = transcript("mp_rust", 120.0, None)
    expect("client never rejoins", ["rejoin"],
           obs(lost, 29, map_change_t=change_t,
               client_log=cli_log(dropped="Disconnecting from 00000000.000000000000:0 (@XBOXLIVE_PARTYENDED) "
                                          "at time 147405"),
               server_log=srv_log(reconnects=False)),
           False, ("client_reconnected", "client_loaded_map", "client_high_slot_after"),
           want_reason="client did not reconnect within")
    # bad: it reconnects (the server sees it again) but never finishes the new level: neither copy of its console
    # shows the cgame init AND the server gets no usercmd from it. One witness alone is not enough - a console
    # file lags its process by up to the game's 4 KB log buffer, which is the whole reason there are two.
    stuck, change_t = transcript("mp_rust", 120.0, 28, lastmsg_after=45000)
    expect("reconnects but never loads the map", ["rejoin"],
           obs(stuck, 29, map_change_t=change_t, client_log=cli_log(loaded=False),
               client_stdout=cli_stdout(loaded=False), server_log=srv_log()),
           False, ("client_loaded_map",), want_reason="never finished loading mp_crash")
    # good: the console copies stop mid-reload (the unflushed tail) but the server still gets usercmds from it -
    # it is in the level, and the verdict says which witness it used
    unflushed, change_t = transcript("mp_rust", 120.0, 28)
    expect("console stops mid-reload, client is playing", ["rejoin"],
           obs(unflushed, 29, map_change_t=change_t, client_log=cli_log(loaded=False), server_log=srv_log()),
           True, want_reason="usercmd")
    # good: only the -stdout copy got that far; it carries no ms stamps, so the verdict keeps the timing out
    stdout_only, change_t = transcript("mp_rust", 120.0, 28)
    expect("the load line is only in the stdout copy", ["rejoin"],
           obs(stdout_only, 29, map_change_t=change_t, client_log=cli_log(loaded=False),
               client_stdout=cli_stdout(), server_log=srv_log()), True, want_reason="finished loading")
    # bad: it rejoins in a low slot - a layout gap, and NOT a reconnect failure (the confusion this file exists
    # to stop: the rejoin checks must all pass and the verdict must not talk about reconnecting)
    low, change_t = transcript("mp_rust", 120.0, 3)
    expect("rejoins in slot 3", ["rejoin"],
           obs(low, 29, map_change_t=change_t, client_log=cli_log(), server_log=srv_log(human_slot=3)),
           False, ("client_high_slot_after",), want_reason="slot 3",
           want_ok_checks=("client_reconnected", "client_loaded_map", "client_no_session_error"))
    # bad: it never got the server's notice at all
    blind, change_t = transcript("mp_rust", 120.0, 28)
    expect("client never saw the change", ["rejoin"],
           obs(blind, 29, map_change_t=change_t, client_log=cli_log(notice=False), server_log=srv_log()),
           False, ("client_followed_change",), want_reason="did not get the notice")
    # bad: no client console log to read at all (the client process never ran) - say so, do not read it as a pass
    nolog, change_t = transcript("mp_rust", 120.0, 28)
    expect("no client console log", ["rejoin"], obs(nolog, 29, map_change_t=change_t, client_log="",
                                                   server_log=srv_log()),
           False, ("client_followed_change",), want_reason="no client console log")
    # bad: it came back with a session-ending error in its console
    errored, change_t = transcript("mp_rust", 120.0, 28)
    expect("client rejoins with an error", ["rejoin"],
           obs(errored, 29, map_change_t=change_t,
               client_log=cli_log() + "\n[   161000] Disconnecting from 00000000.000000000000:0 "
                                      "(@XBOXLIVE_PARTYENDED) at time 161000",
               server_log=srv_log()),
           False, ("client_no_session_error",), want_reason="XBOXLIVE_PARTYENDED")
    # bad: it rejoins, then its process is gone (crash on the level reload)
    dead, change_t = transcript("mp_rust", 120.0, 28, up_after=False)
    expect("client process died", ["rejoin"],
           obs(dead, 29, map_change_t=change_t, client_log=cli_log(), server_log=srv_log()),
           False, ("client_process_up",))
    # bad: nobody was dropped - the change command never restarted the session, so a client that never left
    # would "rejoin" and nothing would be proven
    none_left, change_t = transcript("mp_rust", 120.0, 28, restarted=False)
    expect("session never restarted", ["rejoin"],
           obs(none_left, 29, map_change_t=change_t, client_log=cli_log(), server_log=srv_log(restarts=1)),
           False, ("session_restarted",))
    # bad: the map never changed (the change command landed on the map we were already on)
    same = [(t, status_text("mp_rust", table(28, 28)), True) for t in (20, 40, 60, 80, 100, 120, 140, 160, 200)]
    expect("same map after the change", ["rejoin"],
           obs(same, 29, map_change_t=120.0, client_log=cli_log(notice=False), server_log=srv_log(restarts=1)),
           False, ("map_changed", "session_restarted"))
    # bad: it is back in status and in the level, but its console never shows the fork re-applying the 32-player
    # layout on the new connect - the re-initialization chain stopped halfway, which a final-state check cannot see
    nolayout, change_t = transcript("mp_rust", 120.0, 28)
    expect("rejoin with no layout re-init after the change", ["rejoin"],
           obs(nolayout, 29, map_change_t=change_t, client_log=cli_log(layout=False),
               client_stdout=cli_stdout(layout=False), server_log=srv_log()),
           False, ("client_reinit_sequence",), want_reason="broke at 'layout'",
           want_ok_checks=("client_reconnected", "client_loaded_map", "client_high_slot_after"))
    # bad: status shows it back, but the server's console has no connect for the human guid after its level
    # restart - nobody re-connected, the slot was simply never dropped in what the logs show
    nohand, change_t = transcript("mp_rust", 120.0, 28)
    expect("no server-side connect after the restart", ["rejoin"],
           obs(nohand, 29, map_change_t=change_t, client_log=cli_log(), server_log=srv_log(handshake=False)),
           False, ("client_reinit_sequence",), want_reason="broke at 'server_reconnect'")
    # bad: the only cgame init line after the notice is stamped BEFORE the notice - the load lines belong to the
    # first join, not to the rejoin, so the chain is out of order
    mixed, change_t = transcript("mp_rust", 120.0, 28)
    expect("re-init lines out of order", ["rejoin"],
           obs(mixed, 29, map_change_t=change_t,
               client_log=cli_log(loaded=False) + "\n[   140000] CL_InitCGame:  4.42 seconds",
               client_stdout=cli_stdout(loaded=False), server_log=srv_log()),
           False, ("client_reinit_sequence",), want_reason="broke at 'loaded'")
    # good: the chain is complete - every step present, in order, and the server took the human guid back
    expect("good run chain", ["rejoin"], obs(good, 29, map_change_t=change_t, client_log=cli_log(),
                                             server_log=srv_log()), True,
           want_ok_checks=("client_reinit_sequence",))
    # bad: the server itself went down at the change - baseline must see it
    expect("server died", ["baseline"], obs([(20, status_text("mp_rust", table(28, 28)), True)], 29,
           server_alive=False), False, ("server_alive",))
    # bad: bots never came back after the change
    few, change_t = transcript("mp_rust", 120.0, 28, bots_after=4)
    expect("bots not re-added", ["rejoin"],
           obs(few, 29, map_change_t=change_t, client_log=cli_log(), server_log=srv_log()),
           False, ("players_back_after",))
    # bad: a new crash dump appeared
    dump, change_t = transcript("mp_rust", 120.0, 28)
    expect("new crash dump", ["baseline"], obs(dump, 29, map_change_t=change_t, new_crash_dumps=1),
           False, ("no_new_crash_dumps",))
    # the log files the box hands back: both processes share userraw/console_mp.log*, so the command line each
    # block starts with is what keeps the client's story separate from the server's, and the file name is what
    # keeps the client's two copies of its own console apart (the stdout one carries no ms stamps)
    n += 1
    raw = ("## server.log\n['iw4x.exe' '-dedicated' '-stdout' +set net_port 28971 +map mp_rust]\n"
           "[     5927] ------ Server Initialization ------\n"
           f"## client.log\n['iw4x.exe' '-stdout' +set name live-test iw4x://<test_server>:28971]\n"
           f"{cli_stdout()}\n"
           f"## userraw/console_mp.log\n{cli_log()}\n"
           f"## userraw/console_mp.log.000\n{srv_log()}\n")
    c, co, s = split_logs(raw)
    if ("Server changing map" not in c or "Server Initialization" not in s or "-dedicated" in c
            or "iw4x://" in s or "CL_InitCGame" not in co or "Server Initialization" in co):
        fails.append(f"split_logs: client {len(c)} chars, client stdout {len(co)} chars, server {len(s)} chars "
                     "- wanted the map-change notice on the client side, its stdout copy in the middle and the "
                     "level restarts on the server side")

    # the rejoin case must refuse a setup it cannot judge, not silently pass
    n += 1
    ok, res = verdict(["rejoin"], obs(good, 29))
    if ok or not any(c["name"] == "rejoin_setup" and not c["ok"] for c in res):
        why = "got PASS" if ok else "no rejoin_setup failure"
        fails.append(f"rejoin without --map-change-at: {why}")

    for f in fails:
        print("[self-test] FAIL " + f)
    print(f"[self-test] {'ok' if not fails else 'FAILED'} - {n} checks: good transcript passes, "
          f"{len(fails)} wrong", flush=True)
    return 0 if not fails else 1


# ---------------------------------------------------------------- the live run (GPU box)

def site_get(key):
    """site value from the local site config - same file and $IW4X32_SITE override as the RE tools' site.py; the
    real hosts, IPs and game folders never live in the repo."""
    env = os.environ.get("IW4X32_" + key.upper())
    if env:
        return env
    p = os.environ.get("IW4X32_SITE") or os.path.expanduser("~/.config/iw4x32/site.json")
    if not os.path.isfile(p):
        sys.exit(f"no site config at {p} - fill it in or set IW4X32_{key.upper()}")
    v = json.load(open(p)).get(key)
    if not v:
        sys.exit(f"site config {p} has no {key}")
    return os.path.expanduser(v)


def ssh(host, cmd, timeout=600):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def split_logs(raw):
    """what fetch_logs pulled off the box -> (the client's console log, the client's stdout copy, the server's
    console text). Each block begins with the command line of the process that wrote it, which is the only thing
    that tells the two processes apart now that both share userraw/console_mp.log*: -dedicated is the server, the
    iw4x:// join is the client. Empty blocks (client.log when the client runs without -stdout) drop out; a block
    with both markers (the client never rotated the server's log) goes with whichever command line came first; one
    with neither goes to the client, because reading the server's lines as the client's can only ever fail a
    check, never fake a rejoin. Within the client's own text the file name tells the two copies apart."""
    parts = re.split(r"^## (\S+)\n", raw, flags=re.M)
    cli, cliout, srv = [], [], []
    for name, text in zip(parts[1::2], parts[2::2]):
        if not text.strip():
            continue
        ded, join = text.find("-dedicated"), text.find("iw4x://")
        if 0 <= ded < join or (join < 0 <= ded):
            srv.append(text)
        elif name.endswith(CLI_OUT):
            cliout.append(text)
        else:
            cli.append(text)
    return "\n".join(cli), "\n".join(cliout), "\n".join(srv)


def fetch_logs(host, d):
    """the client's and the server's own console lines, filtered to CLI_EVENT, from the four files the run leaves
    behind (see split_logs for which of them belongs to whom)."""
    _, raw = ssh(host, f"cd {d} && for f in server.log {CLI_OUT} {CLI_LOG} {CLI_LOG}.000; do "
                       f'[ -f "$f" ] && echo "## $f" && tail -c 400000 "$f" | grep -a -E \'{CLI_EVENT}\'; done',
                 timeout=180)
    return split_logs(raw)


def flush_client_log(host, d, rcpy, n=FLUSH_LINES):
    """make the client print, so its own console buffer reaches the disk. The game writes its console through a
    4 KB stdio buffer and flushes only when that buffer is full, which is why the last lines of a level reload -
    the cgame init line the rejoin verdict reads - are the first thing missing from the file (box-checked: the
    client's console log sat at 108730 bytes for two minutes while the client went on printing, then jumped to
    112892 with the missing 'CL_InitCGame' line in it after 60 `say` lines; killing the process flushes nothing).
    `say` over rcon prints in every client's console, so push enough of them to carry the pending bytes out."""
    ssh(host, f"cd {d} && for i in $(seq 1 {n}); do {rcpy} \"say log-flush-$i {'a' * 60}\"; done", timeout=900)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll")
    ap.add_argument("--bots", type=int, default=28)
    ap.add_argument("--client", action="store_true")
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--map", default="mp_rust")
    ap.add_argument("--map-change-at", type=float, default=None, metavar="MIN",
                    help="force a map change after MIN minutes, re-add the bots, and require everyone back "
                         "afterwards (the rotate path wants the run to be a minute longer)")
    ap.add_argument("--map-change-to", default="mp_crash", metavar="MAP",
                    help="the map to change to (must differ from --map; the test game folder has the stock mp_ maps)")
    ap.add_argument("--change-via", choices=("rotate", "map"), default="rotate",
                    help="how to trigger the change: rcon map_rotate over a rotation the copy's server.cfg names "
                         "(what a real match does at its end) or rcon map <map2> directly")
    ap.add_argument("--case", default=None, metavar="LIST",
                    help="comma list of " + ",".join(CASES) + " (default: baseline, + rejoin when --client and "
                         "--map-change-at are both given)")
    ap.add_argument("--self-test", action="store_true", help="judge the recorded transcripts, no box needed")
    ap.add_argument("--save-logs", metavar="DIR", default=None,
                    help="copy the run's server and client console logs here before the folder is removed")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(self_test())
    if not a.dll:
        sys.exit("--dll is required (or use --self-test)")
    cases = a.case.split(",") if a.case else ["baseline"] + (["rejoin"] if a.client and a.map_change_at is not None else [])
    for c in cases:
        if c not in CASES:
            sys.exit(f"no such case: {c} (known: {','.join(CASES)})")
    dll = os.path.abspath(a.dll)
    if not os.path.isfile(dll):
        sys.exit(f"no such DLL: {dll}")
    host = site_get("gpu_ssh")
    base = site_get("game_base")   # the box's base test game folder (stock exe + game files), relative to its
    #                              home: a box layout detail, so it lives in the site config, not in the repo
    run = f"t{int(time.time())}"
    d = f"Games/live-test/{run}"
    print(f"[aiboi_test] {run}: dll {dll} bots {a.bots} client {a.client} {a.minutes} min cases {','.join(cases)}",
          flush=True)
    # 1. lock (wait up to 1 h for another test), throwaway folder, DLL in
    rc, o = ssh(host, f"mkdir -p Games/live-test && exec 9>Games/live-test/.lock && flock -w 3600 9 && "
                      f"cp -al {base} {d} && rm -f {d}/iw4x.dll {d}/server-v2.log {d}/client-v2.log "
                      f"{d}/userraw/console_mp.log* && "
                      f"ls {d}/minidumps 2>/dev/null | wc -l > {d}/.dumps0 && echo locked-ok", timeout=3700)
    if "locked-ok" not in o:
        sys.exit(f"setup failed: {o[-400:]}")
    if a.change_via == "rotate":
        # the engine reads sv_maprotation when the LEVEL starts - setting it over rcon mid-level changes the dvar
        # but not the rotation the next map_rotate uses (checked on the box: set it to mp_rust mid-level, the
        # rotate still went to the map named at level start). So the rotation goes into the copy's server.cfg,
        # and it names only the map we want next: with two maps named, map_rotate restarts the current one.
        # server.cfg in the copy is a HARD LINK into the base folder, so write a new file, never append in place.
        rc, o = ssh(host, f"cd {d} && {{ cat userraw/server.cfg; "
                          f"printf '\nset sv_maprotation \"map {a.map_change_to}\"\n'; "
                          f"}} > .cfg.new && mv .cfg.new userraw/server.cfg && tail -2 userraw/server.cfg")
        if a.map_change_to not in o:
            sys.exit(f"could not write the rotation into the copy's server.cfg: {o[-200:]}")
    subprocess.run(["scp", "-q", dll, f"{host}:{d}/iw4x.dll"], check=True)
    port = 28971
    srv = (f"cd {d} && (WINEPREFIX=$HOME/.wine-livetest-srv WINEDEBUG=-all setsid nohup wine iw4x.exe -dedicated -stdout "
           f"+set sv_lanonly 1 +set net_port {port} +exec server.cfg +set sv_maxclients 32 +set party_maxplayers 32 "
           f"+set party_enable 0 +set logfile 1 +map {a.map} > server.log 2>&1 < /dev/null & echo $! > .srvpid)")
    rcpy = f"python3 rc.py --port {port}"                 # the game folder's rcon helper (password from server.cfg)
    cli_log_txt = cli_out_txt = srv_log_txt = ""
    try:
        ssh(host, srv)
        time.sleep(60)
        ssh(host, f"cd {d} && {rcpy} 'spawnBot {a.bots}'")
        if a.client:
            ssh(host, f"cd {d} && export DISPLAY=:0 XAUTHORITY=\"$(ls /run/user/$(id -u)/.mutter-Xwaylandauth.* | head -1)\" "
                      f"__GLX_VENDOR_LIBRARY_NAME=mesa WINEPREFIX=$HOME/.wine-livetest-cli WINEDEBUG=-all && "
                      f"(setsid nohup wine iw4x.exe -stdout +set r_fullscreen 0 +set r_mode 1280x720 "
                      f"+set name {CLIENT_NAME} "
                      f"iw4x://127.0.0.1:{port} > client.log 2>&1 < /dev/null & echo $! > .clipid)")
        want = a.bots + (1 if a.client else 0)
        t0 = time.time()
        alive_all, change_t = True, None
        polls = []
        while time.time() < t0 + a.minutes * 60:
            if a.map_change_at is not None and change_t is None and time.time() - t0 >= a.map_change_at * 60:
                if a.change_via == "rotate":
                    # the first map_rotate after a manual +map only restarts the current map - the rotation
                    # system has not seen this level before. the second one follows the rotation. (box-checked)
                    ssh(host, f"cd {d} && {rcpy} map_rotate")
                    time.sleep(50)
                    ssh(host, f"cd {d} && {rcpy} map_rotate")
                else:
                    ssh(host, f"cd {d} && {rcpy} 'map {a.map_change_to}'")
                change_t = time.time() - t0
                time.sleep(45)
                ssh(host, f"cd {d} && {rcpy} 'spawnBot {a.bots}'")
            time.sleep(20)
            _, st = ssh(host, f"cd {d} && {rcpy} status")
            mp, rows = parse_status(st)
            if mp is None:
                alive_all = False
                break
            up = True
            if a.client:
                _, cu = ssh(host, f"cd {d} && [ -f .clipid ] && kill -0 $(cat .clipid) 2>/dev/null && echo up")
                up = "up" in cu
            t = time.time() - t0
            print(f"[aiboi_test] poll t={t:.0f}s map={mp} players={len(rows)} "
                  f"client={'slot ' + str(client_slot(rows)) if a.client else '-'}", flush=True)
            polls.append({"t": t, "map": mp, "rows": rows, "client_up": up})
        _, dumps = ssh(host, f"cd {d} && echo $(( $(ls minidumps 2>/dev/null | wc -l) - $(cat .dumps0) ))")
        new_dumps = int(dumps.split()[-1]) if dumps.split() and dumps.split()[-1].lstrip("-").isdigit() else 0
        if a.client:
            print("[aiboi_test] pushing the client's console buffer out with rcon say lines", flush=True)
            flush_client_log(host, d, rcpy)
            time.sleep(3)
        cli_log_txt, cli_out_txt, srv_log_txt = fetch_logs(host, d)
        # the dll's server-init line, counted where it is printed: the server's own stdout, once per process
        _, mk = ssh(host, f"cd {d} && grep -a -c '{MAP_INIT}' server.log 2>/dev/null || echo 0")
        marker = int(mk.split()[-1]) if mk.split() and mk.split()[-1].isdigit() else 0
        obs_rec = {"polls": polls, "want": want, "client": a.client, "map_change_t": change_t,
                   "map_to": a.map_change_to, "new_crash_dumps": new_dumps, "server_alive": alive_all,
                   "client_log": cli_log_txt, "client_stdout": cli_out_txt, "server_log": srv_log_txt,
                   "iw4x32_marker": marker}
        ok, res = verdict(cases, obs_rec)
        facts = rejoin_facts(obs_rec) if a.client and change_t is not None else None
        cli_story = client_story_all([cli_log_txt, cli_out_txt], a.map_change_to)
        report = {"players_max": max((len(p["rows"]) for p in polls), default=0), "players_wanted": want,
                  "maps_seen": sorted({p["map"] for p in polls if p["map"]}), "polls": len(polls),
                  "client_console_lines": cli_story["lines"], "client_console_copies": cli_story["copies"],
                  "iw4x32_marker_lines": marker, "new_crash_dumps": new_dumps}
        if facts:
            report.update({"client_disconnected": facts["disconnected"],
                           "client_reconnected": facts["reconnected"],
                           "client_reconnect_s": None if facts["reconnect_s"] is None else round(facts["reconnect_s"]),
                           "client_loaded_map": facts["loaded"],
                           "client_load_s": None if facts["load_s"] is None else round(facts["load_s"]),
                           "client_lastmsg_ms": facts["lastmsg"],
                           "client_errors": [l[:90] for _ms, l in facts["fatal"]],
                           "client_slot_before": facts["slot_before"], "client_slot_after": facts["slot_after"],
                           "first_failure": next((c["name"] for c in res if not c["ok"]), None)})
    finally:
        if a.save_logs:
            os.makedirs(a.save_logs, exist_ok=True)
            subprocess.run(["scp", "-q", f"{host}:{d}/server.log", f"{host}:{d}/client.log",
                            f"{host}:{d}/userraw/console_mp.log*", a.save_logs + "/"], capture_output=True)
            print(f"[aiboi_test] logs copied to {a.save_logs}", flush=True)
        _, tail = ssh(host, f"cd {d} && grep -a -E 'IW4x32:|ERROR|rror|xception|Crash' server.log | tail -8; "
                            f"tail -6 server.log", timeout=60)
        # the client's own last console lines, straight out of the text the verdict was judged on - the copy that
        # got furthest (empty if the run died before fetch_logs - then there is nothing honest to print for it)
        tail_src = max((cli_log_txt, cli_out_txt), key=len)
        cli_tail = "\n".join(tail_src.splitlines()[-16:]) if tail_src else ""
        ssh(host, f"cd {d} && for f in .clipid .srvpid; do [ -f $f ] && kill $(cat $f) 2>/dev/null; done; sleep 5; "
                  f"for p in srv cli; do WINEPREFIX=$HOME/.wine-livetest-$p wineserver -k 2>/dev/null; done; "
                  f"cd ~ && rm -rf {d}", timeout=120)
        print("[aiboi_test] server console:\n" + "\n".join("  " + l[:160] for l in tail.splitlines()), flush=True)
        if cli_tail:
            print("[aiboi_test] client console:\n" + "\n".join("  " + l[:160] for l in cli_tail.splitlines()), flush=True)
    for c in res:
        print(f"[aiboi_test] {'ok  ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}", flush=True)
    print("[aiboi_test] " + verdict_line(cases, obs_rec, ok, res), flush=True)
    print(f"[aiboi_test] {'PASS' if ok else 'FAIL'} {report}", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
