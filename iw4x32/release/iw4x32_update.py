#!/usr/bin/env python3
"""IW4x-32 auto-update (Linux; Windows: iw4x32_update.ps1 - same steps). Run by play-linux.sh before the game starts.

  1. picks the game to start - IW4x-32 (default) or vanilla IW4x: a --vanilla / --iw4x32 flag, then IW4X32_MODE,
     then a start menu (5 s, the last choice is the default), then the choice remembered in mode.txt. The choice
     made here is remembered; no other code path touches mode.txt.
  2. mode iw4x32 - reads latest.json of the newest IW4x-32 release (GitHub, shaunypnz/iw4x-32); if it is newer
     than this kit (README.txt line 1 "IW4x-32 vX.Y"):
       - IW4x itself older than the release needs: runs the official IW4x launcher with --skip-launch (update only),
         but ONLY when the newest IW4x is exactly the version this IW4x-32 release is made for - if IW4x is
         already newer, nothing is updated (an IW4x-32 update for it follows) and you keep playing the current pair
       - downloads the changed kit files, checks every SHA-256 against latest.json, swaps them in, installs
         files/iw4x.dll into the game folder (IW4x-32 v2.0 is one DLL: iw4x.exe stays the official IW4x one)
     repair: if the game folder has the official iw4x.dll again (e.g. the IW4x launcher was used), puts IW4x-32
     back; an official dll that is not the backed-up one but is the one the newest release is made for: it becomes
     the backup; an official dll newer than that: vanilla IW4x starts this time (mode.txt stays as it is);
     an iw4x.exe left over from an IW4x-32 v1.x install is restored from backup/
  3. mode vanilla: puts the official iw4x.dll back and runs the official IW4x launcher (downloaded when missing),
     which updates IW4x and starts the game itself
Nothing is downloaded or changed when everything is current. No network: the game just starts.
Exit 0 = nothing changed, 10 = this kit was updated (play-linux.sh restarts itself), 20 = vanilla IW4x was started
by its launcher (do not start the game), 1 = error (game still starts). Skip: IW4X32_NO_UPDATE=1, IW4X32_NO_MENU=1"""
import hashlib, io, json, os, re, select, shutil, subprocess, sys, tarfile, tempfile, urllib.parse, urllib.request

REPO = "shaunypnz/iw4x-32"
MANIFEST = os.environ.get("IW4X32_UPDATE_URL", f"https://raw.githubusercontent.com/{REPO}/main/latest.json")
IW4X_LATEST = os.environ.get("IW4X32_IW4X_LATEST_URL", "https://api.github.com/repos/iw4x/iw4x-client/releases/latest")
LAUNCHER_RELEASE = os.environ.get("IW4X32_LAUNCHER_RELEASE_URL",
                                  "https://api.github.com/repos/iw4x/launcher/releases/latest")
V1_EXE = "2609c2687dd2ffb3f32c7687ed04f57b38ef6879c14b1c546faf8bfd8f35ea6b"   # iw4x.exe of an IW4x-32 v1.x install
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
    # the game process is named iw4x.exe under Wine/Proton
    # only THIS game folder's iw4x.exe counts (a dedicated server or another install elsewhere does not)
    r = subprocess.run(["pgrep", "-x", "iw4x.exe"], capture_output=True, text=True)
    for pid in r.stdout.split():
        try:
            if os.path.realpath(f"/proc/{pid}/cwd") == os.path.realpath(GAME):
                return True
        except OSError:
            pass
    return False


def install_ours():
    """copy files/iw4x.dll into the game folder (the official one is in backup/)"""
    src = os.path.join(KIT, "files", "iw4x.dll")
    tmp = os.path.join(GAME, "iw4x.dll.iw4x32-new")
    shutil.copy2(src, tmp)
    os.replace(tmp, os.path.join(GAME, "iw4x.dll"))
    if sha(os.path.join(GAME, "iw4x.dll")) != sha(src):
        raise SystemExit("installing iw4x.dll failed")


def restore_v1_exe(official_exe):
    """an IW4x-32 v1.x install put its own iw4x.exe in the game folder; v2.0 runs the official IW4x one
    (official_exe = None: any backup made by an installer is good enough)"""
    if sha(os.path.join(GAME, "iw4x.exe")) != V1_EXE:
        return
    bak = sha(os.path.join(KIT, "backup", "iw4x.exe"))
    if not bak or (official_exe and bak != official_exe):
        say("an older IW4x-32 replaced your iw4x.exe and there is no backup of it - run the IW4x launcher once to repair")
        return
    say("an older IW4x-32 replaced iw4x.exe - putting your official one back")
    shutil.copy2(os.path.join(KIT, "backup", "iw4x.exe"), os.path.join(GAME, "iw4x.exe"))


def repair(m):
    """the IW4x launcher (or a repair) put the official iw4x.dll back: re-install IW4x-32 if it is the backed-up
    one or the one the newest release is made for; an IW4x newer than that returns vanilla"""
    restore_v1_exe((m or {}).get("official", {}).get("iw4x.exe"))
    ours, now = sha(os.path.join(KIT, "files", "iw4x.dll")), sha(os.path.join(GAME, "iw4x.dll"))
    if now == ours:
        return False
    bak = sha(os.path.join(KIT, "backup", "iw4x.dll"))
    if now == bak and bak:
        say("the official IW4x iw4x.dll is installed again - putting IW4x-32 back")
        install_ours()
        return True
    if not bak or not now:
        say("not installed yet - run install-linux.sh once")
        return False
    if m and now == m.get("official", {}).get("iw4x.dll"):
        say("IW4x was updated by the official launcher - putting IW4x-32 back")
        shutil.copy2(os.path.join(GAME, "iw4x.dll"), os.path.join(KIT, "backup", "iw4x.dll"))
        install_ours()
        return True
    say("IW4x was updated to a newer version than IW4x-32 supports yet - starting vanilla IW4x this time.")
    return "vanilla"


def ensure_launcher():
    """the official IW4x launcher in the game folder, downloaded from its GitHub release when it is not there"""
    for name in ("iw4x-launcher", "iw4x-launcher.exe", "iw4x-launcher-x86.exe"):
        p = os.path.join(GAME, name)
        if os.path.exists(p):
            return p
    try:
        rel = json.loads(get(LAUNCHER_RELEASE))
        asset = next(a for a in rel["assets"] if a["name"].endswith("-x86_64-linux-glibc.tar.xz"))
        data = get(asset["browser_download_url"], timeout=120)
    except Exception as e:
        say(f"the IW4x launcher is not in the game folder and could not be downloaded ({type(e).__name__})")
        return None
    if "sha256:" + hashlib.sha256(data).hexdigest() != (asset.get("digest") or "").lower():
        say("download check failed for the IW4x launcher")
        return None
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tf:
        mem = next((m for m in tf.getmembers() if m.isfile() and os.path.basename(m.name) == "iw4x-launcher"), None)
        if not mem:
            say("the IW4x launcher download has no iw4x-launcher in it")
            return None
        body = tf.extractfile(mem).read()
    tmp = os.path.join(GAME, "iw4x-launcher.iw4x32-new")
    open(tmp, "wb").write(body)
    os.replace(tmp, os.path.join(GAME, "iw4x-launcher"))
    os.chmod(os.path.join(GAME, "iw4x-launcher"), 0o755)
    say(f"downloaded the official IW4x launcher {rel.get('tag_name', '')}")
    return os.path.join(GAME, "iw4x-launcher")


def run_launcher(launcher, args):
    cmd = [launcher] + list(args)
    if launcher.endswith(".exe"):
        cmd = ["wine"] + cmd
    return subprocess.run(cmd, cwd=GAME)


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
    launcher = ensure_launcher()
    if not launcher:
        return False
    say(f"updating IW4x to {m['iw4x']} (official IW4x launcher, update only) ...")
    r = run_launcher(launcher, ["--skip-launch"])
    if sha(os.path.join(GAME, "iw4x.dll")) != want["iw4x.dll"]:
        say(f"the IW4x launcher (exit {r.returncode}) did not install IW4x {m['iw4x']} - you are on the official "
            "IW4x files now; start again later to retry")
        return None
    os.makedirs(os.path.join(KIT, "backup"), exist_ok=True)
    shutil.copy2(os.path.join(GAME, "iw4x.dll"), os.path.join(KIT, "backup", "iw4x.dll"))
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


def read_mode():
    try:
        w = open(os.path.join(KIT, "mode.txt"), encoding="utf-8", errors="replace").read().split()
        return w[0] if w and w[0] in ("vanilla", "iw4x32") else "iw4x32"
    except OSError:
        return "iw4x32"


def write_mode(m):
    try:
        open(os.path.join(KIT, "mode.txt"), "w").write(m + "\n")
    except OSError:
        pass


def start_menu(default):
    print("Start which game?")
    print("  [1] IW4x-32  - 32-player servers (and normal ones)")
    print("  [2] Vanilla IW4x - the official IW4x, always the latest version")
    print(f"Enter = {default} (starts in 5 s): ", end="", flush=True)
    line = sys.stdin.readline().strip() if select.select([sys.stdin], [], [], 5)[0] else ""
    print()
    return {"1": "iw4x32", "iw4x32": "iw4x32", "2": "vanilla", "vanilla": "vanilla"}.get(line.lower(), default)


def select_mode():
    """flag, IW4X32_MODE, menu, remembered mode - in that order; only a mode chosen now goes into mode.txt"""
    flag = next((a[2:] for a in sys.argv[1:] if a in ("--vanilla", "--iw4x32")), None)
    if flag:
        write_mode(flag)
        return flag
    if os.environ.get("IW4X32_MODE") in ("vanilla", "iw4x32"):
        write_mode(os.environ["IW4X32_MODE"])
        return os.environ["IW4X32_MODE"]
    have = read_mode()
    if os.environ.get("IW4X32_NO_MENU") == "1" or os.environ.get("IW4X32_NO_UPDATE") == "1" \
            or not sys.stdin.isatty():
        return have
    mode = start_menu(have)
    write_mode(mode)
    return mode


def start_vanilla():
    """official IW4x: put the official iw4x.dll back, then the official launcher updates IW4x and starts the game"""
    ours, now = sha(os.path.join(KIT, "files", "iw4x.dll")), sha(os.path.join(GAME, "iw4x.dll"))
    bak = sha(os.path.join(KIT, "backup", "iw4x.dll"))
    if now == ours and bak:
        say("putting the official IW4x iw4x.dll back - the official launcher starts from that")
        tmp = os.path.join(GAME, "iw4x.dll.iw4x32-off")
        shutil.copy2(os.path.join(KIT, "backup", "iw4x.dll"), tmp)
        os.replace(tmp, os.path.join(GAME, "iw4x.dll"))
    restore_v1_exe(None)
    launcher = ensure_launcher()
    if not launcher:
        return 1
    say("starting vanilla IW4x (official IW4x launcher) ...")
    run_launcher(launcher, ["--skip-launch"] if os.environ.get("IW4X32_NO_START") == "1" else [])
    return 20


def main():
    if select_mode() == "vanilla":
        return start_vanilla()
    if os.environ.get("IW4X32_NO_UPDATE") == "1":
        return 0
    have = installed_version()
    try:
        m = json.loads(get(MANIFEST))
    except Exception as e:
        say(f"no update check ({type(e).__name__}) - starting IW4x-32 {have}")
        m = None
    if m and vtuple(m["version"]) > vtuple(have) and game_running():
        say("the game is running - update next time")
        return 0
    if repair(m) == "vanilla":
        return start_vanilla()
    if not m or vtuple(m["version"]) <= vtuple(have):
        return 0
    ok = update_iw4x(m)
    if ok is None:
        return 1
    if not ok:
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
