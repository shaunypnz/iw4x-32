#!/usr/bin/env python3
"""
mapchange_rejoin.py - does THIS build's iw4x.dll keep a real client on a 32-slot server across a map change?

    python3 iw4x32/tools/mapchange_rejoin.py [--bots 28] [--minutes 13] [--endgame-at MIN] [--dll PATH]

Runs the live game on the GPU box (site config "gpu_ssh"): stock iw4x.exe + this build's iw4x.dll, 32 slots,
--bots bots, and one real client on the box's desktop. The bots go in first, so the client takes a slot >= 18 -
the slots the stock 18-wide party/session layer does not cover, which is where this bug lived. The match then
changes the map with `rcon map_rotate` (--rotate-at, the reported scenario) and then keeps watching: the client
follows the change, comes back, and an unfixed build used to walk out to the lobby with @XBOXLIVE_PARTYENDED a
few minutes later (427 s, 479 s and 720 s in the three runs that reproduced it).

PASS = the server stayed up, no new crash dumps, the client was still in the game (in rcon status) at the end,
and its console shows no walk-out. It shares the GPU box's test lock with tools-re/aiboi_test.py.
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
WALKOUT = "PARTYENDED|Disconnecting from|Com_Error"


def ssh(cmd, timeout=600):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", HOST, cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll", default=os.path.join(ROOT, "build", "bin", "Win32", "Release", "iw4x.dll"))
    ap.add_argument("--bots", type=int, default=28)
    ap.add_argument("--minutes", type=float, default=13.0)
    ap.add_argument("--rotate-at", type=float, default=2.0, metavar="MIN",
                    help="change the map this far in (0 = don't)")
    ap.add_argument("--endgame-at", type=float, default=0.0, metavar="MIN",
                    help="also force the end of the match this far in (0 = let it end by itself)")
    ap.add_argument("--scorelimit", type=int, default=5)
    ap.add_argument("--map", default="mp_rust")
    a = ap.parse_args()
    dll = os.path.abspath(a.dll)
    if not os.path.isfile(dll):
        sys.exit("no such DLL: %s" % dll)

    run = "rejoin-%d" % int(time.time())
    d = "Games/live-test/%s" % run
    port = 28972
    rcpy = "python3 rc.py --port %d" % port
    t0 = time.time()
    stamp = lambda: "[%6.0fs]" % (time.time() - t0)
    print("[rejoin] %s: dll %s bots %d %.0f min" % (run, dll, a.bots, a.minutes), flush=True)

    rc, o = ssh("mkdir -p Games/live-test && exec 9>Games/live-test/.lock && flock -w 3600 9 && "
                "cp -al %s %s && rm -f %s/iw4x.dll %s/server.log %s/client.log && "
                "ls %s/minidumps 2>/dev/null | wc -l > %s/.dumps0 && echo locked-ok"
                % (BASE, d, d, d, d, d, d), timeout=3700)
    if "locked-ok" not in o:
        sys.exit("setup failed: %s" % o[-400:])

    ok, report = False, {}
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
        print(stamp(), "server up, map", map_now, flush=True)

        ssh("cd %s && %s 'spawnBot %d'" % (d, rcpy, a.bots))
        time.sleep(10)
        ssh("cd %s && export DISPLAY=:0 XAUTHORITY=\"$(ls /run/user/$(id -u)/.mutter-Xwaylandauth.* | head -1)\" "
            "__GLX_VENDOR_LIBRARY_NAME=mesa WINEPREFIX=$HOME/.wine-livetest-cli WINEDEBUG=-all && "
            "(setsid nohup wine iw4x.exe -stdout +set r_fullscreen 0 +set r_mode 1280x720 +set name live-test "
            "iw4x://127.0.0.1:%d > client.log 2>&1 < /dev/null & echo $! > .clipid)" % (d, port))

        end, humans, slots = t0 + a.minutes * 60, [], []
        ended = a.endgame_at <= 0
        rotated = a.rotate_at <= 0
        while time.time() < end:
            if not rotated and time.time() - t0 >= a.rotate_at * 60:
                ssh("cd %s && %s 'map_rotate'" % (d, rcpy))
                print(stamp(), "rcon map_rotate - the level restarts and the client reloads", flush=True)
                rotated = True
            if not ended and time.time() - t0 >= a.endgame_at * 60:
                ssh("cd %s && %s 'set scr_dom_scorelimit %d'" % (d, rcpy, a.scorelimit))
                print(stamp(), "rcon set scr_dom_scorelimit %d - the match will end and rotate" % a.scorelimit,
                      flush=True)
                ended = True
            time.sleep(15)
            _, st = ssh("cd %s && %s status" % (d, rcpy))
            rows = [l for l in st.splitlines() if re.match(r"^\s*\d+\s+-?\d+\s+\d+", l)]
            hum = [int(l.split()[0]) for l in rows if " bot" not in l.lower()]
            humans.append(bool(hum))
            slots += hum
            print(stamp(), "players %d humans %s" % (len(rows), hum or "-"), flush=True)

        _, dumps = ssh("cd %s && echo $(( $(ls minidumps 2>/dev/null | wc -l) - $(cat .dumps0) ))" % d)
        new_dumps = int(dumps.split()[-1]) if dumps.split()[-1].lstrip("-").isdigit() else 0
        _, walk = ssh("cd %s && grep -a -c -E '%s' client.log" % (d, WALKOUT))
        walkouts = int(walk.split()[-1]) if walk.split()[-1].isdigit() else 0
        _, tail = ssh("cd %s && grep -a -E '%s' client.log | tail -3" % (d, WALKOUT))
        _, st = ssh("cd %s && %s status" % (d, rcpy))
        alive = "map:" in st
        in_game = sum(humans[-4:]) >= 3  # still in the game over the last minute

        report = {"server_alive": alive, "new_crash_dumps": new_dumps, "walkouts_in_client_log": walkouts,
                  "client_in_game_last_min": in_game, "client_slot_max": max(slots) if slots else -1}
        ok = alive and new_dumps == 0 and walkouts == 0 and in_game and report["client_slot_max"] >= 18
        if tail:
            print("[rejoin] client walk-out lines:\n" + "\n".join("  " + l[:160] for l in tail.splitlines()),
                  flush=True)
    finally:
        _, tail = ssh("cd %s && grep -a -E 'IW4x32:|rror|xception|Rotating map|ShutdownGame|"
                      "Server Initialization' server.log | tail -6; tail -4 server.log" % d, timeout=60)
        ssh("cd %s && for f in .clipid .srvpid; do [ -f $f ] && kill $(cat $f) 2>/dev/null; done; sleep 5; "
            "for p in srv cli; do WINEPREFIX=$HOME/.wine-livetest-$p wineserver -k 2>/dev/null; done; "
            "cd ~ && rm -rf %s" % (d, d), timeout=120)
        print("[rejoin] server console:\n" + "\n".join("  " + l[:160] for l in tail.splitlines()), flush=True)
    print("[rejoin] %s %s" % ("PASS" if ok else "FAIL", report), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
