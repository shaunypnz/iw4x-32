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
     rotation when the level starts, so it has to be there before +map) and the test fires rcon map_rotate.
     --change-via map fires rcon map <map2> directly. Either way the bots are re-added afterwards.
  5. watches for --minutes: player count, highest slot in use, server alive, client process up, new crash dumps
  6. stops everything it started (by PID), removes the folder, prints a report and exits 0 = pass

Test cases (--case, default: baseline, plus rejoin when --client and --map-change-at are both given). Every case
judges one observation record - what the run saw - and prints one line per check:
  baseline  server alive the whole run, no new crash dump, every bot in, and with --client the client holds a
            slot >= 18 (only the 32-player engine changes can put a client that high).
  rejoin    the client comes back by itself after a forced map change: the map in `status` changed, the session
            really restarted (a level restart drops every client, so the bots answering after it carry new guids -
            without that a client that never left would "rejoin"), the client is in `status` again under its own
            name within REJOIN_MAX_S, still in a slot >= 18 (the client-side 32-player layout survived the level
            reload), its process is still up, its console log shows it took the server's map-change notice and
            reloaded, and the bots are back too. This is the case for the "client does not come back after a map
            change" bug.

--self-test runs the cases over the recorded transcripts at the bottom of this file: the good one must pass, and
every bad one must fail the check that names its problem - a probe that always reads "perfect" is broken."""
import argparse, json, os, re, subprocess, sys, time

CLIENT_NAME = "live-test"                 # the test client joins with +set name <CLIENT_NAME>
SLOT_32 = 18                              # a slot >= 18 exists only with the 32-player layout live
REJOIN_MAX_S = 150.0                      # a stock client follows a map change within about a minute
MAP_INIT = "iw4x32: .*slot server"        # the dll's server-init line (printed once per process, not per level)
CLI_LOG = "userraw/console_mp.log"        # console log of whatever game process opens it last (see --save-logs)
CLI_FOLLOW = "Server changing map"        # the client got the server's map-change notice and reloads with it


# ---------------------------------------------------------------- the judging half (no box, no game)

def chk(name, ok, detail):
    return {"name": name, "ok": bool(ok), "detail": detail}


ROW = re.compile(r"^\s*(\d+)\s+(-?\d+)\s+(-?\d+)\s+(\S+)\s+(.*)$")


def parse_status(text):
    """rcon `status` -> (map or None, [(slot, guid, name), ...]). Bots carry a bot<N> guid; the header, the ----
    line and the map line do not match ROW, so they drop out. Colour codes are stripped from the name."""
    m = re.search(r"^\s*map:\s*(\S+)", text, re.M)
    rows = []
    for l in text.splitlines():
        g = ROW.match(l)
        if not g:
            continue
        rest = g.group(5).split()
        rows.append((int(g.group(1)), g.group(4), re.sub(r"\^\d", "", rest[0]) if rest else ""))
    return (m.group(1) if m else None), rows


def humans(rows):
    return [r for r in rows if not r[1].lower().startswith("bot")]


def bot_guids(rows):
    return {r[1].lower() for r in rows if r[1].lower().startswith("bot")}


def client_slot(rows):
    """slot of our test client in a status row list, None when it is not on the server."""
    for slot, _guid, name in humans(rows):
        if name.lower() == CLIENT_NAME:
            return slot
    return None


def case_baseline(o):
    best = max((len(p["rows"]) for p in o["polls"]), default=0)
    top = max([s for p in o["polls"] for s, _g, _n in humans(p["rows"])], default=-1)
    yield chk("server_alive", o["server_alive"], "every status poll answered")
    yield chk("no_new_crash_dumps", o["new_crash_dumps"] == 0, f"{o['new_crash_dumps']} new minidump(s)")
    yield chk("players_in", best >= o["want"], f"most {best} of {o['want']} wanted")
    if o["client"]:
        yield chk("client_slot_32", top >= SLOT_32, f"highest human slot {top}, needs >= {SLOT_32}")


def case_rejoin(o):
    """the client must rejoin the session on its own after the map change, in a 32-player slot, process up."""
    if not o["client"] or o["map_change_t"] is None:
        yield chk("rejoin_setup", False, "the rejoin case needs --client and --map-change-at")
        return
    before = [p for p in o["polls"] if p["t"] <= o["map_change_t"]]
    after = [p for p in o["polls"] if p["t"] > o["map_change_t"]]
    maps = [p["map"] for p in o["polls"] if p["map"]]
    back = [p for p in after if client_slot(p["rows"]) is not None]
    # a level restart drops every client, and IW4x gives each spawnBot the next guid in the session - so the bots
    # that answer after the change are not the bots that answered before it. That is what proves the session
    # really restarted: without it a client that never left would "rejoin".
    gone = bot_guids(before[-1]["rows"]) if before else set()
    new = set().union(*[bot_guids(p["rows"]) for p in after]) if after else set()

    yield chk("client_in_before", any(client_slot(p["rows"]) is not None for p in before),
              f"{CLIENT_NAME} in status before the change")
    yield chk("map_changed", len(set(maps)) >= 2, f"maps in status: {maps[0] if maps else '?'} -> {maps[-1] if maps else '?'}")
    yield chk("session_restarted", bool(gone) and bool(new) and not (gone & new),
              f"bot guids before {sorted(gone)[:2]}..{len(gone)} vs after {sorted(new)[:2]}..{len(new)} - "
              "a level restart drops every client, so none may be shared")
    yield chk("client_rejoined", bool(back), f"{CLIENT_NAME} in status again after the change: {bool(back)}")
    if back:
        dt = back[0]["t"] - o["map_change_t"]
        yield chk("rejoin_within", dt <= REJOIN_MAX_S, f"back after {dt:.0f} s, limit {REJOIN_MAX_S:.0f} s")
        yield chk("rejoin_slot_32", client_slot(back[-1]["rows"]) >= SLOT_32,
                  f"slot {client_slot(back[-1]['rows'])} after the change, needs >= {SLOT_32} "
                  "(the client-side 32-player layout survived the reload)")
    else:
        yield chk("rejoin_within", False, "never came back")
        yield chk("rejoin_slot_32", False, "never came back")
    yield chk("client_process_up", bool(after) and after[-1]["client_up"], "client process still up at the end")
    yield chk("client_follow_line", o["client_follow"] >= 1,
              f"{o['client_follow']} '{CLI_FOLLOW} {o['map_to']}' line(s) in {CLI_LOG}* - the client-side reload ran")
    players_after = max((len(p["rows"]) for p in after), default=0)
    yield chk("players_back_after", players_after >= o["want"], f"most {players_after} of {o['want']} after the change")


CASES = {"baseline": case_baseline, "rejoin": case_rejoin}


def verdict(cases, o):
    res = [c for name in cases for c in CASES[name](o)]
    return all(c["ok"] for c in res), res


# ---------------------------------------------------------------- the recorded transcripts (--self-test)

def status_text(mp, entries):
    """entries [(slot, guid, name), ...] -> rcon status text. The address column stays a placeholder: no real
    IPs in the repo, and nothing here reads it."""
    lines = [f"map: {mp}",
             " num score ping guid                             name            lastmsg address               qport rate",
             "--- ----- ---- -------------------------------- --------------- ------- --------------------- ----- -----"]
    for slot, guid, name in entries:
        lines.append(f"{slot:>3} {0:>4} {12:>3} {guid:>32} {name + '^7':<15} {60950:>6} {'0:<LAN-IP>':<21} {0:>4} {25000:>5}")
    return "\n".join(lines)


def table(bots, client_slot_no, guid0=0):
    """a status table: bots in slots 0..bots-1 with session guids bot{guid0}.., our client in client_slot_no
    (None = not on the server). A level restart drops every bot and the re-add names the next ones, so a real
    change shows guid0 = bots after it and guid0 = 0 before it."""
    rows = [(i, f"bot{guid0 + i}", "Lunarion") for i in range(bots)]
    if client_slot_no is not None:
        rows.append((client_slot_no, "AB12cd34EF567890", CLIENT_NAME))
    return rows


def obs(polls, want, map_change_t=None, map_to="mp_crash", new_crash_dumps=0, server_alive=True, client=True,
        client_follow=1, iw4x32_marker=1):
    """polls: [(t, status text, client process up)] -> the observation record the cases judge."""
    ps = []
    for t, txt, up in polls:
        mp, rows = parse_status(txt)
        ps.append({"t": t, "map": mp, "rows": rows, "client_up": up})
    return {"polls": ps, "want": want, "client": client, "map_change_t": map_change_t, "map_to": map_to,
            "new_crash_dumps": new_crash_dumps, "server_alive": server_alive, "client_follow": client_follow,
            "iw4x32_marker": iw4x32_marker}


def transcript(mp, change_t, client_after, bots=28, up_after=True, bots_after=None, mp_after="mp_crash",
               restarted=True):
    """a 5-minute run: bots + client in, map change at change_t (lands on mp_after), client_after = the slot the
    client is back in (None = it never came back), bots_after = how many bots the re-add brought back,
    restarted = the level restart dropped everyone (new bot guids), polls every 20 s."""
    polls = [(t, status_text(mp, table(bots, bots)), True) for t in (20, 40, 60, 80, 100, 120)]
    after = bots if bots_after is None else bots_after
    guid0 = bots if restarted else 0
    polls += [(t, status_text(mp_after, table(after, client_after, guid0)), up_after)
              for t in (140, 160, 200, 240, 280, 300)]
    return polls, change_t


def self_test():
    n, fails = 0, []

    def expect(what, cases, o, want_ok, want_fails=()):
        nonlocal n
        n += 1
        ok, res = verdict(cases, o)
        bad_names = {c["name"] for c in res if not c["ok"]}
        if ok != want_ok or not set(want_fails) <= bad_names:
            fails.append(f"{what}: got {'PASS' if ok else 'FAIL'} {sorted(bad_names)}, wanted "
                         f"{'PASS' if want_ok else 'FAIL'} with {sorted(want_fails) or 'no failures'}")

    # the parser sees the real status shape
    mp, rows = parse_status(status_text("mp_rust", table(28, 28)))
    n += 1
    if mp != "mp_rust" or len(rows) != 29 or client_slot(rows) != 28 or len(humans(rows)) != 1:
        fails.append(f"parse_status: map {mp}, {len(rows)} rows, client slot {client_slot(rows)}, "
                     f"{len(humans(rows))} human(s) - wanted mp_rust, 29, 28, 1")

    good, change_t = transcript("mp_rust", 120.0, 28)
    expect("good run", ["baseline", "rejoin"], obs(good, 29, map_change_t=change_t), True)

    # bad: the client never rejoins (the bug this case is for) - it is off the server after the change
    lost, change_t = transcript("mp_rust", 120.0, None)
    expect("client never rejoins", ["rejoin"], obs(lost, 29, map_change_t=change_t, client_follow=0),
           False, ("client_rejoined", "rejoin_within", "rejoin_slot_32", "client_follow_line"))
    # bad: it rejoins in a low slot - the client-side layout fell back to 18 players on the reload
    low, change_t = transcript("mp_rust", 120.0, 3)
    expect("rejoins in slot 3", ["rejoin"], obs(low, 29, map_change_t=change_t), False, ("rejoin_slot_32",))
    # bad: it rejoins, then its process is gone (crash on the level reload)
    dead, change_t = transcript("mp_rust", 120.0, 28, up_after=False)
    expect("client process died", ["rejoin"], obs(dead, 29, map_change_t=change_t), False, ("client_process_up",))
    # bad: nobody was dropped - the change command never restarted the session, so a client that never left
    # would "rejoin" and nothing would be proven
    none_left, change_t = transcript("mp_rust", 120.0, 28, restarted=False)
    expect("session never restarted", ["rejoin"], obs(none_left, 29, map_change_t=change_t),
           False, ("session_restarted",))
    # bad: the map never changed (the change command landed on the map we were already on)
    same = [(t, status_text("mp_rust", table(28, 28)), True) for t in (20, 40, 60, 80, 100, 120, 140, 160, 200)]
    expect("same map after the change", ["rejoin"], obs(same, 29, map_change_t=120.0),
           False, ("map_changed", "session_restarted"))
    # bad: the server itself went down at the change - baseline must see it
    expect("server died", ["baseline"], obs([(20, status_text("mp_rust", table(28, 28)), True)], 29,
           server_alive=False), False, ("server_alive",))
    # bad: bots never came back after the change
    few, change_t = transcript("mp_rust", 120.0, 28, bots_after=4)
    expect("bots not re-added", ["rejoin"], obs(few, 29, map_change_t=change_t), False, ("players_back_after",))
    # bad: a new crash dump appeared
    dump, change_t = transcript("mp_rust", 120.0, 28)
    expect("new crash dump", ["baseline"], obs(dump, 29, map_change_t=change_t, new_crash_dumps=1),
           False, ("no_new_crash_dumps",))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll")
    ap.add_argument("--bots", type=int, default=28)
    ap.add_argument("--client", action="store_true")
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--map", default="mp_rust")
    ap.add_argument("--map-change-at", type=float, default=None, metavar="MIN",
                    help="rcon map <map2> after MIN minutes, re-add the bots, and require everyone back afterwards")
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
    try:
        ssh(host, srv)
        time.sleep(60)
        ssh(host, f"cd {d} && {rcpy} 'spawnBot {a.bots}'")
        if a.client:
            ssh(host, f"cd {d} && export DISPLAY=:0 XAUTHORITY=\"$(ls /run/user/$(id -u)/.mutter-Xwaylandauth.* | head -1)\" "
                      f"__GLX_VENDOR_LIBRARY_NAME=mesa WINEPREFIX=$HOME/.wine-livetest-cli WINEDEBUG=-all && "
                      f"(setsid nohup wine iw4x.exe +set r_fullscreen 0 +set r_mode 1280x720 +set name {CLIENT_NAME} "
                      f"iw4x://127.0.0.1:{port} > client.log 2>&1 < /dev/null & echo $! > .clipid)")
        want = a.bots + (1 if a.client else 0)
        t0 = time.time()
        alive_all, change_t = True, None
        polls = []
        while time.time() < t0 + a.minutes * 60:
            if a.map_change_at is not None and change_t is None and time.time() - t0 >= a.map_change_at * 60:
                ssh(host, f"cd {d} && {rcpy} "
                          + ("map_rotate" if a.change_via == "rotate" else f"'map {a.map_change_to}'"))
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
        _, inits = ssh(host, f"cd {d} && grep -a -c '{MAP_INIT}' server.log")
        marker = int(inits.split()[-1]) if inits.split() and inits.split()[-1].isdigit() else 0
        follow = 0
        if a.client and change_t is not None:
            _, fc = ssh(host, f"cd {d} && cat {CLI_LOG}* 2>/dev/null | grep -a -c '{CLI_FOLLOW} {a.map_change_to}'")
            follow = int(fc.split()[-1]) if fc.split() and fc.split()[-1].isdigit() else 0
        obs_rec = {"polls": polls, "want": want, "client": a.client, "map_change_t": change_t,
                   "map_to": a.map_change_to, "new_crash_dumps": new_dumps, "server_alive": alive_all,
                   "client_follow": follow, "iw4x32_marker": marker}
        ok, res = verdict(cases, obs_rec)
        report = {"players_max": max((len(p["rows"]) for p in polls), default=0), "players_wanted": want,
                  "client_slot": client_slot(polls[-1]["rows"]) if polls and a.client else None,
                  "maps_seen": sorted({p["map"] for p in polls if p["map"]}), "polls": len(polls),
                  "client_follow_lines": follow, "iw4x32_marker_lines": marker, "new_crash_dumps": new_dumps}
    finally:
        if a.save_logs:
            os.makedirs(a.save_logs, exist_ok=True)
            subprocess.run(["scp", "-q", f"{host}:{d}/server.log", f"{host}:{d}/client.log",
                            f"{host}:{d}/userraw/console_mp.log*", a.save_logs + "/"], capture_output=True)
            print(f"[aiboi_test] logs copied to {a.save_logs}", flush=True)
        _, tail = ssh(host, f"cd {d} && grep -a -E 'IW4x32:|ERROR|rror|xception|Crash' server.log | tail -8; "
                            f"tail -6 server.log", timeout=60)
        cli_tail = ""
        if a.client:
            cli_grep = "| grep -a -E 'onnect|isconnect|PARTYENDED|hanging map|rror|xception' | tail -16"
            _, cli_tail = ssh(host, f"cd {d} && cat $(ls -t {CLI_LOG}* 2>/dev/null) 2>/dev/null {cli_grep}", timeout=60)
        ssh(host, f"cd {d} && for f in .clipid .srvpid; do [ -f $f ] && kill $(cat $f) 2>/dev/null; done; sleep 5; "
                  f"for p in srv cli; do WINEPREFIX=$HOME/.wine-livetest-$p wineserver -k 2>/dev/null; done; "
                  f"cd ~ && rm -rf {d}", timeout=120)
        print("[aiboi_test] server console:\n" + "\n".join("  " + l[:160] for l in tail.splitlines()), flush=True)
        if cli_tail:
            print("[aiboi_test] client console:\n" + "\n".join("  " + l[:160] for l in cli_tail.splitlines()), flush=True)
    for c in res:
        print(f"[aiboi_test] {'ok  ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}", flush=True)
    print(f"[aiboi_test] {'PASS' if ok else 'FAIL'} {report}", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
