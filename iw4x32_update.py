#!/usr/bin/env python3
"""IW4x-32 auto-update (Linux; Windows: iw4x32_update.ps1 - same steps). Run by play-linux.sh before the game starts.

  1. reads latest.json of the newest IW4x-32 release (GitHub, shaunypnz/iw4x-32)
  2. if it is newer than this kit (README.txt line 1 "IW4x-32 vX.Y"):
       - IW4x itself older than the release needs: runs the official IW4x launcher with --skip-launch (update only),
         but ONLY when the newest IW4x is exactly the version this IW4x-32 release is made for - if IW4x is
         already newer, nothing is updated (an IW4x-32 update for it follows) and you keep playing the current pair
       - downloads the changed kit files, checks every SHA-256 against latest.json, swaps them in, installs
         files/iw4x.exe + files/iw4x.dll into the game folder
  3. repair: if the game folder has the official files again (e.g. the IW4x launcher was used), puts IW4x-32 back
Nothing is downloaded or changed when everything is current. No network: the game just starts.
Exit 0 = nothing changed, 10 = this kit was updated (play-linux.sh restarts itself), 1 = error (game still starts).
Skip: IW4X32_NO_UPDATE=1"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.parse, urllib.request

REPO = "shaunypnz/iw4x-32"
MANIFEST = os.environ.get("IW4X32_UPDATE_URL", f"https://raw.githubusercontent.com/{REPO}/main/latest.json")
IW4X_LATEST = os.environ.get("IW4X32_IW4X_LATEST_URL", "https://api.github.com/repos/iw4x/iw4x-client/releases/latest")
KIT = os.path.dirname(os.path.abspath(__file__))
GAME = os.environ.get("IW4X32_GAME") or os.path.dirname(KIT)


def say(msg):
    print(f"[IW4x-32 update] {msg}", flush=True)


def sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except OSError:
        return None


def get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "iw4x32-updater", "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def installed_version():
    try:
        m = re.match(r"IW4x-32 (v[\d.]+)", open(os.path.join(KIT, "README.txt"), encoding="utf-8", errors="replace").readline())
        return m.group(1) if m else "v0"
    except OSError:
        return "v0"


def game_running():
    # by process name only (Wine/Proton name the game process iw4x.exe); a command line merely mentioning it is not it
    return subprocess.run(["pgrep", "-x", "iw4x.exe"], capture_output=True).returncode == 0


def install_ours():
    """copy files/iw4x.exe + iw4x.dll into the game folder (the official ones are in backup/)"""
    for f in ("iw4x.exe", "iw4x.dll"):
        tmp = os.path.join(GAME, f + ".iw4x32-new")
        shutil.copy2(os.path.join(KIT, "files", f), tmp)
        os.replace(tmp, os.path.join(GAME, f))
        if sha(os.path.join(GAME, f)) != sha(os.path.join(KIT, "files", f)):
            raise SystemExit(f"installing {f} failed")


def repair():
    """the IW4x launcher (or a repair) put the official files back: re-install IW4x-32 if they are the backed-up ones"""
    ours = {f: sha(os.path.join(KIT, "files", f)) for f in ("iw4x.exe", "iw4x.dll")}
    now = {f: sha(os.path.join(GAME, f)) for f in ours}
    if now == ours:
        return False
    backup = {f: sha(os.path.join(KIT, "backup", f)) for f in ours}
    if now == backup and None not in backup.values():
        say("the official IW4x files are installed again - putting IW4x-32 back")
        install_ours()
        return True
    if None in backup.values():
        say("not installed yet - run install-linux.sh once")
    return False


def iw4x_launcher():
    for name in ("iw4x-launcher", "iw4x-launcher.exe", "iw4x-launcher-x86.exe"):
        p = os.path.join(GAME, name)
        if os.path.exists(p):
            return p
    return None


def update_iw4x(m):
    """bring the official IW4x to the version the release is made for (only if that is the newest IW4x)"""
    want = m["official"]
    if sha(os.path.join(KIT, "backup", "iw4x.dll")) == want["iw4x.dll"]:
        return True
    try:
        latest = json.loads(get(IW4X_LATEST))["tag_name"]
    except Exception as e:
        say(f"cannot check the IW4x version ({type(e).__name__}) - not updating now")
        return False
    if latest != m["iw4x"]:
        say(f"IW4x {latest} is out; IW4x-32 for it is not ready yet - keeping your current version")
        return False
    launcher = iw4x_launcher()
    if not launcher:
        say("the IW4x launcher was not found in the game folder - update IW4x yourself, then start again")
        return False
    say(f"updating IW4x to {m['iw4x']} (official IW4x launcher, update only) ...")
    cmd = [launcher, "--skip-launch"]
    if launcher.endswith(".exe"):
        cmd = ["wine"] + cmd
    r = subprocess.run(cmd, cwd=GAME)
    got = {f: sha(os.path.join(GAME, f)) for f in ("iw4x.exe", "iw4x.dll")}
    if got != want:
        say(f"the IW4x launcher (exit {r.returncode}) did not install IW4x {m['iw4x']} - you are on the official "
            "IW4x files now; start again later to retry")
        return None
    os.makedirs(os.path.join(KIT, "backup"), exist_ok=True)
    for f in ("iw4x.exe", "iw4x.dll"):
        shutil.copy2(os.path.join(GAME, f), os.path.join(KIT, "backup", f))
    return True


def update_kit(m):
    base = m["base_url"]
    todo = [p for p, h in m["files"].items() if sha(os.path.join(KIT, p)) != h]
    say(f"IW4x-32 {m['version']}: downloading {len(todo)} file(s) ...")
    stage = tempfile.mkdtemp(prefix=".update-", dir=KIT)
    try:
        for p in todo:
            data = get(base + urllib.parse.quote(p), timeout=120)
            if hashlib.sha256(data).hexdigest() != m["files"][p]:
                raise SystemExit(f"download check failed for {p} - nothing was changed")
            dst = os.path.join(stage, p)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(data)
        for p in todo:                                   # all verified: swap in (rename = safe for a running script)
            dst = os.path.join(KIT, p)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            mode = os.stat(dst).st_mode if os.path.exists(dst) else (0o755 if p.endswith((".sh", ".py")) else 0o644)
            os.replace(os.path.join(stage, p), dst)
            os.chmod(dst, mode)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main():
    if os.environ.get("IW4X32_NO_UPDATE") == "1":
        return 0
    have = installed_version()
    try:
        m = json.loads(get(MANIFEST))
    except Exception as e:
        say(f"no update check ({type(e).__name__}) - starting IW4x-32 {have}")
        repair()
        return 0
    if vtuple(m["version"]) <= vtuple(have):
        repair()
        return 0
    if game_running():
        say("the game is running - update next time")
        return 0
    ok = update_iw4x(m)
    if ok is None:
        return 1
    if not ok:
        repair()
        return 0
    update_kit(m)
    install_ours()
    say(f"updated to IW4x-32 {m['version']} on IW4x {m['iw4x']}")
    return 10


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        if isinstance(e.code, str):
            say(f"ERROR: {e.code}")
            sys.exit(1)
        raise
    except Exception as e:
        say(f"ERROR: {type(e).__name__}: {e} - starting the game anyway")
        sys.exit(1)
