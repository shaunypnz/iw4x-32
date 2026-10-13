#!/usr/bin/env python3
"""
mapchange_rejoin.py - does THIS build's iw4x.dll keep a real client on a 32-slot server across a MAP CHANGE?

    python3 iw4x32/tools/mapchange_rejoin.py [--bots 28] [--minutes 13] [--change-at 2]
                                             [--map-to mp_broadcast] [--dll PATH] [--kill-client-at MIN]

Runs the live game on the GPU box (site config "gpu_ssh"): stock iw4x.exe + this build's iw4x.dll, 32 slots,
--bots bots, and one real client on the box's desktop. The bots go in first, so the client lands in a slot
>= 18 - the slots the stock 18-wide party/session layer does not cover, which is where this bug lived.

At --change-at the tool changes the level for real: `rcon map <map-to>` (a DIFFERENT map, so the server
really shuts the level down and brings up a new one - "ShutdownGame" then "------ Server Initialization
------" - and the client has to follow it by itself). `--rotate-cmd map_rotate` gives the reported command
instead, but on a one-map playlist that is not a level change at all, which is why the earlier controls
proved nothing. The tool counts the level restarts in the server log and checks the map name actually
changed, so a run that never changed the level FAILS instead of passing vacuously.

--kill-client-at is the bad-case probe: it kills the client (by the pid file this tool wrote) and the run
then has to report the human gone, which proves the measurement can see the failure it is looking for.

PASS = server up, no new crash dumps, the level really restarted, the client followed it and was back in
the game (in rcon status) in the last minute, and its console shows no walk-out (@XBOXLIVE_PARTYENDED /
Disconnecting from / Com_Error). Shares the GPU box's test lock with tools-re/aiboi_test.py.
"""
import argparse
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                # the worktree
TOOLS = os.path.join(os.path.expanduser("~"), "Projects", "IW4x-32", "tools-re")                   # iw4x_site.py
sys.path.insert(0, TOOLS)
import iw4x_site as site  # noqa: E402

HOST = site.get("gpu_ssh")
BASE = "Games/MW2-IW4x32-v2"                    # on the box: stock exe + game files
WALKOUT = "PARTYENDED|Disconnecting from|Com_Error|quit reading client log"
FOLLOW = "Server changing map|loadingnewmap"
LEAVE = "Disconnecting|Server timed out|EXE_|ERROR:|match ended|Match Ended"


def ssh(cmd, timeout=600):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", HOST, cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def num(out):
    t = out.split()
    return int(t[-1]) if t and t[-1].lstrip("-").isdigit() else 0


def restart_count(d):
    # IW4x-32: how many times the server has brought a level up - our DLL prints "iw4x32: <n>-slot server"
    # from SV_SpawnServer, so counting that line counts level restarts. server.log is the server's stdout,
    # which Wine block-buffers and the teardown kills, so its tail (often including the restart we are after)
    # never lands in the file; the engine's own logfile (+set logfile 1 -> server-v2.log) is tried too and
    # can lose its tail the same way, which is why the caller also takes maps_seen - 1. Count both logs and
    # keep the larger.
    _, out = ssh("cd %s && grep -a -c -- '-slot server' server.log 2>/dev/null; "
                 "grep -a -c -- '-slot server' server-v2.log 2>/dev/null" % d)
    vals = [num(l) for l in out.splitlines() if l.strip()]
    return max(vals) if vals else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll", default=os.path.join(ROOT, "build", "bin", "Win32", "Release", "iw4x.dll"))
    ap.add_argument("--bots", type=int, default=28)
    ap.add_argument("--minutes", type=float, default=13.0)
    ap.add_argument("--change-at", type=float, default=2.0, metavar="MIN", help="change the level this far in (0 = don't)")
    ap.add_argument("--map-to", default="mp_broadcast", help="the map to change to (a real level change)")
    ap.add_argument("--rotate-cmd", default="", metavar="RCMDCON",
                    help="use this rcon command instead of `map <map-to>` (e.g. map_rotate)")
    ap.add_argument("--map", default="mp_rust")
    ap.add_argument("--scorelimit", type=int, default=0, metavar="N",
                    help="rcon set scr_dom_scorelimit N at the start, so the match ENDS and the server rotates "
                         "by itself (the reported scenario)")
    ap.add_argument("--endgame-at", type=float, default=0.0, metavar="MIN",
                    help="set the scorelimit this far in instead of at the start")
    ap.add_argument("--kill-client-at", type=float, default=0.0, metavar="MIN",
                    help="bad-case probe: kill the client this far in (0 = don't)")
    ap.add_argument("--tag", default="rejoin")
    a = ap.parse_args()
    dll = os.path.abspath(a.dll)
    if not os.path.isfile(dll):
        sys.exit("no such DLL: %s" % dll)
    if not a.rotate_cmd and a.map_to == a.map:
        sys.exit("mapchange_rejoin: --map-to must differ from --map (or pass --rotate-cmd)")

    run = "%s-%d" % (a.tag, int(time.time()))
    d = "Games/live-test/%s" % run
    port = 28972
    rcpy = "python3 rc.py --port %d" % port
    t0 = time.time()
    stamp = lambda: "[%6.0fs]" % (time.time() - t0)
    print("[rejoin] %s: dll %s bots %d %.0f min, level change at %.1f min -> %s"
          % (run, dll, a.bots, a.minutes, a.change_at, a.rotate_cmd or ("map " + a.map_to)), flush=True)

    rc, o = ssh("mkdir -p Games/live-test && exec 9>Games/live-test/.lock && flock -w 3600 9 && "
                "cp -al %s %s && rm -f %s/iw4x.dll %s/server.log %s/client.log && "
                "ls %s/minidumps 2>/dev/null | wc -l > %s/.dumps0 && echo locked-ok"
                % (BASE, d, d, d, d, d, d), timeout=3700)
    if "locked-ok" not in o:
        sys.exit("setup failed: %s" % o[-400:])

    ok, report, restarts0, dumps0 = False, {}, 0, 0
    try:
        subprocess.run(["scp", "-q", dll, "%s:%s/iw4x.dll" % (HOST, d)], check=True)
        ssh("cd %s && (WINEPREFIX=$HOME/.wine-livetest-srv WINEDEBUG=-all setsid nohup wine iw4x.exe -dedicated "
            "-stdout +set sv_lanonly 1 +set net_port %d +exec server.cfg +set sv_maxclients 32 "
            "+set party_maxplayers 32 +set party_enable 0 +set logfile 1 +map %s > server.log 2>&1 < /dev/null "
            "& echo $! > .srvpid)" % (d, port, a.map))
        map_now = None
        for _ in range(20):
            time.sleep(6)
            _, st = ssh("cd %s && %s status" % (d, rcpy))
            m = re.search(r"map: (\S+)", st)
            if m:
                map_now = m.group(1)
                break
        if not map_now:
            sys.exit("server never came up: %s" % st[-400:])
        restarts0 = restart_count(d)
        print(stamp(), "server up, map %s, level restarts so far %d" % (map_now, restarts0), flush=True)

        ssh("cd %s && %s 'spawnBot %d'" % (d, rcpy, a.bots))
        time.sleep(10)
        if a.scorelimit and a.endgame_at <= 0:
            ssh("cd %s && %s 'set scr_dom_scorelimit %d'" % (d, rcpy, a.scorelimit))
            print(stamp(), "rcon set scr_dom_scorelimit %d - the match will end and the server will rotate"
                  % a.scorelimit, flush=True)
        ssh("cd %s && export DISPLAY=:0 XAUTHORITY=\"$(ls /run/user/$(id -u)/.mutter-Xwaylandauth.* | head -1)\" "
            "__GLX_VENDOR_LIBRARY_NAME=mesa WINEPREFIX=$HOME/.wine-livetest-cli WINEDEBUG=-all && "
            "(setsid nohup wine iw4x.exe -stdout +set r_fullscreen 0 +set r_mode 1280x720 +set name live-test "
            "iw4x://127.0.0.1:%d > client.log 2>&1 < /dev/null & echo $! > .clipid)" % (d, port))

        end, humans, slots, seen = t0 + a.minutes * 60, [], [], {}
        changed = a.change_at <= 0
        killed = a.kill_client_at <= 0
        ended = a.endgame_at <= 0
        while time.time() < end:
            if not changed and time.time() - t0 >= a.change_at * 60:
                cmd = a.rotate_cmd or ("map " + a.map_to)
                ssh("cd %s && %s '%s'" % (d, rcpy, cmd))
                print(stamp(), "rcon %s - the level restarts, the client has to follow it" % cmd, flush=True)
                changed = True
            if a.scorelimit and a.endgame_at > 0 and not ended and time.time() - t0 >= a.endgame_at * 60:
                ssh("cd %s && %s 'set scr_dom_scorelimit %d'" % (d, rcpy, a.scorelimit))
                print(stamp(), "rcon set scr_dom_scorelimit %d" % a.scorelimit, flush=True)
                ended = True
            if not killed and time.time() - t0 >= a.kill_client_at * 60:
                ssh("cd %s && kill $(cat .clipid) 2>/dev/null" % d)
                print(stamp(), "bad-case probe: killed the client (pid file .clipid)", flush=True)
                killed = True
            time.sleep(15)
            _, st = ssh("cd %s && %s status" % (d, rcpy))
            rows = [l for l in st.splitlines() if re.match(r"^\s*\d+\s+-?\d+\s+\d+", l)]
            hum = [int(l.split()[0]) for l in rows if " bot" not in l.lower()]
            humans.append(bool(hum))
            slots += hum
            m = re.search(r"map: (\S+)", st)
            if m:
                seen[m.group(1)] = seen.get(m.group(1), 0) + 1
            print(stamp(), "players %d humans %s map %s" % (len(rows), hum or "-", m.group(1) if m else "?"),
                  flush=True)

        _, dumps = ssh("cd %s && ls minidumps 2>/dev/null | wc -l; cat .dumps0" % d)
        vals = dumps.split()
        new_dumps = num(vals[0]) - num(vals[-1]) if len(vals) >= 2 else 0
        _, walk = ssh("cd %s && grep -a -c -E '%s' client.log" % (d, WALKOUT))
        walkouts = num(walk)
        _, tail = ssh("cd %s && grep -a -E '%s' client.log | tail -4" % (d, WALKOUT))
        _, follow = ssh("cd %s && grep -a -c -E '%s' client.log" % (d, FOLLOW))
        restarts = restart_count(d)
        _, st = ssh("cd %s && %s status" % (d, rcpy))
        alive = "map:" in st
        in_game = sum(humans[-4:]) >= 3          # still in the game over the last minute
        maps = list(seen)
        # IW4x-32: maps_seen - 1 is the live-measured floor for "the level really restarted", because neither
        # server log can be trusted to still hold the line by the time we grep it - see restart_count.
        report = {"server_alive": alive, "new_crash_dumps": new_dumps, "walkouts_in_client_log": walkouts,
                  "client_in_game_last_min": in_game, "client_slot_max": max(slots) if slots else -1,
                  "level_restarts": max(restarts - restarts0, len(maps) - 1), "maps_seen": maps,
                  "client_followed_change": num(follow) > 0}
        if a.kill_client_at > 0:
            ok = alive and not in_game and report["level_restarts"] >= 0
            print("[rejoin] bad-case probe: the run must show the human GONE - in_game_last_min=%s"
                  % in_game, flush=True)
        else:
            forced_other = a.change_at > 0 and not a.rotate_cmd and a.map_to != a.map
            ok = (alive and new_dumps == 0 and walkouts == 0 and in_game
                  and report["client_slot_max"] >= 18 and report["level_restarts"] >= 1
                  and (not forced_other or len(maps) >= 2))
        if tail:
            print("[rejoin] client walk-out lines:\n" + "\n".join("  " + l[:200] for l in tail.splitlines()),
                  flush=True)
        _, why = ssh("cd %s && grep -a -E '%s' client.log | tail -12" % (d, LEAVE), timeout=60)
        print("[rejoin] client console - why it left (last 12):\n"
              + "\n".join("  " + l[:200] for l in why.splitlines()), flush=True)
        logs = os.path.join(ROOT, ".scratch", run)
        os.makedirs(logs, exist_ok=True)
        for f in ("client.log", "server.log"):
            try:
                subprocess.run(["scp", "-q", "%s:%s/%s" % (HOST, d, f), os.path.join(logs, f)], timeout=120)
                print("[rejoin] saved %s/%s" % (logs, f), flush=True)
            except Exception as e:  # noqa: BLE001
                print("[rejoin] could not save %s: %s" % (f, e), flush=True)
    finally:
        _, tail = ssh("cd %s && grep -a -E 'IW4x32:|iw4x32:|rror|xception|Rotating map|ShutdownGame|Server "
                      "Initialization|changing map|Match|End Game|endgame|disconnect|EXE_' server.log | tail -14; "
                      "echo --- client console tail:; tail -20 client.log" % d, timeout=60)
        ssh("cd %s && for f in .clipid .srvpid; do [ -f $f ] && kill $(cat $f) 2>/dev/null; done; sleep 5; "
            "for p in srv cli; do WINEPREFIX=$HOME/.wine-livetest-$p wineserver -k 2>/dev/null; done; "
            "cd ~ && rm -rf %s" % (d, d), timeout=120)
        print("[rejoin] server console / client console tail:\n"
              + "\n".join("  " + l[:200] for l in tail.splitlines()), flush=True)
    print("[rejoin] %s %s" % ("PASS" if ok else "FAIL", report), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
