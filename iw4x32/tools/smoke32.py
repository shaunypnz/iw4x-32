#!/usr/bin/env python3
"""
smoke32.py - does THIS build's iw4x.dll turn a STOCK iw4x.exe into a 32-player dedicated server?

    python3 iw4x32/tools/smoke32.py [--duration 240] [--bots 31]

Runs the IW4x-32 repo's tools-re/run_server.py with the pristine r5154 iw4x.exe (iw4x.exe.orig32) and
build/bin/Win32/Release/iw4x.dll from this worktree, 32 slots, 31 bots. Fails unless the server reached
the map, 31 bots were in (rcon status), it never crashed, and the DLL reported that it patched the
engine (the exe on disk is the stock one, so only the DLL can have done it).
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the worktree
TOOLS = os.path.join(os.path.expanduser("~"), "Projects", "IW4x-32", "tools-re")      # run_server.py lives there
STOCK_EXE = "iw4x.exe.orig32"                                                        # pristine r5154, md5 9c42ffa4...


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=240.0)
    ap.add_argument("--bots", type=int, default=31)
    ap.add_argument("--maxclients", type=int, default=32)
    ap.add_argument("--tag", default="iw4x32-smoke")
    ap.add_argument("--run-server", default=os.path.join(TOOLS, "run_server.py"))
    a = ap.parse_args()

    dll = os.path.join(ROOT, "build", "bin", "Win32", "Release", "iw4x.dll")
    if not os.path.exists(dll):
        sys.exit("smoke32: no %s - build first (tools-re/build_iw4x_fork.sh)" % os.path.relpath(dll, ROOT))
    if not os.path.exists(a.run_server):
        sys.exit("smoke32: %s not found" % a.run_server)

    cmd = [sys.executable, a.run_server, "--exe", STOCK_EXE, "--dll", os.path.abspath(dll),
           "--maxclients", str(a.maxclients), "--bots", str(a.bots),
           "--duration", str(a.duration), "--tag", a.tag]
    print("smoke32: " + " ".join(cmd), flush=True)
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=a.duration + 600)
    out = run.stdout + run.stderr
    print(out[-4000:])
    if run.returncode != 0:
        sys.exit("smoke32: run_server.py exited %d" % run.returncode)

    m = re.search(r"saved: (.+)\.\*", out)
    if not m:
        sys.exit("smoke32: run_server.py reported no run files")
    base = m.group(1)
    events = open(base + ".events.txt").read()
    console = open(base + ".console.txt").read() if os.path.exists(base + ".console.txt") else ""

    bad = []
    summary = [l for l in events.splitlines() if "SUMMARY" in l]
    if not summary:
        bad.append("no SUMMARY line in %s.events.txt" % base)
    else:
        s = summary[-1]
        if "map_up=yes" not in s:
            bad.append("the server never reached the map (%s)" % s)
        if "crashed=yes" in s or "alive_at_end=False" in s:
            bad.append("the server crashed / was gone at the end (%s)" % s)

    # the DLL must say it patched the stock engine
    if not re.search(r"iw4x32:", console, re.I):
        bad.append("the console shows no iw4x32: line - the DLL did not patch the engine")

    # bots in: the widest rcon status poll (rows are "slot ping score name ...")
    rows = [int(m) for m in re.findall(r"rcon status \((\d+) client rows\)", events)]
    if not rows:
        bad.append("no rcon status poll in the run")
    elif max(rows) < a.bots:
        bad.append("only %d clients in status, need %d" % (max(rows), a.bots))

    if bad:
        print("smoke32: FAILED (%s)" % base)
        for b in bad:
            print("  " + b)
        print("  logs: %s.console.txt / %s.events.txt" % (base, base))
        return 1
    print("smoke32: ok - map up, %d clients in status, no crash (%s)" % (max(rows), base))
    return 0


if __name__ == "__main__":
    sys.exit(main())
