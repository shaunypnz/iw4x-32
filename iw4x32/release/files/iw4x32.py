#!/usr/bin/env python3
"""IW4x-32 for Linux / Steam Deck - setup, start menu, auto-update, play, host a server, uninstall: all of it is
this file. IW4x-32.sh runs it. Windows: iw4x32.ps1 next to it does the same steps.

  ./IW4x-32.sh                          first time: sets everything up; then the start menu
  ./IW4x-32.sh --play                   IW4x-32 (32-player servers, and normal ones)
  ./IW4x-32.sh --vanilla                vanilla IW4x (the official IW4x launcher updates and starts it)
  ./IW4x-32.sh --server [port]          32-player dedicated server (port 28960, runs under Wine)
  ./IW4x-32.sh --vanilla-server [port]  normal 18-player IW4x server
  ./IW4x-32.sh --setup [game folder]    do the setup again, e.g. for another game folder
  ./IW4x-32.sh --uninstall              put the official IW4x files back, remove the menu entries
  ./IW4x-32.sh --fix                    the game crashed / hangs and Steam will not start it: close what is left
  --no-update  skip the update check     --dry  only print what would be started
  --direct     Steam install: run iw4x.exe with the game's Proton even when the Steam launch option is set
  anything else goes to the game, e.g.  +connect 1.2.3.4:28960

Setup (the first start does it by itself): finds MW2 (the folder this IW4x-32 folder is in, then every Steam
library: native, Snap, Flatpak), copies IW4x-32 to <game>/IW4x-32 (when that game already has this IW4x-32 or a
newer one, that one is started instead), lets the OFFICIAL IW4x launcher install IW4x when there is none (IW4x-32
never downloads IW4x's own files), backs up the official iw4x.dll, installs files/iw4x.dll (iw4x.exe stays the
official one) and makes the menu entries.
Versions: IW4x-32's iw4x.dll is built for one IW4x release (x, e.g. r5278); your official IW4x is y. Both are read
from the dlls themselves. x = y: all good. Otherwise vanilla IW4x runs y and IW4x-32 runs its own x build; a y
older than x is updated with the official launcher first.
Every start: checks GitHub for a new IW4x-32 (5 s, no network = just start) and installs it with every file's SHA-256
checked; puts IW4x-32 back when the IW4x launcher's file check replaced it. The official IW4x launcher only runs when
it is needed (it checks GitHub, which allows 60 requests an hour): to install or update IW4x, or for vanilla IW4x -
at most every 15 minutes with its online check, in between with --skip-remote.
A crash: game processes left behind (crash reporter, wineserver, Steam's reaper) keep Steam saying MW2 is running.
Before every start they are closed, [6] in the menu / --fix does it on its own, and after the game closes the
launcher offers [R] to start it again - no need to restart Steam.
Steam (Proton): the game runs in its own Proton prefix. With the Steam launch option
    bash -c 'exec "${@/iw4mp.exe/iw4x.exe}"' -- %command%
Steam starts it (and the Play button in Steam works too); without it, the game's Proton is run directly.
Test hooks: IW4X32_GAME, IW4X32_STEAM, IW4X32_UPDATE_URL, IW4X32_LAUNCHER_RELEASE_URL,
IW4X32_NO_START=1 (print the command, start nothing), IW4X32_NO_SHORTCUTS=1, IW4X32_YES=1 (uninstall without asking)."""
import glob, hashlib, io, json, os, re, select, shlex, shutil, signal, subprocess, sys, tarfile, tempfile, time
import urllib.parse, urllib.request

REPO = "shaunypnz/iw4x-32"
OFFICIAL_VER = "r5292"
OFFICIAL_DLL = "890a310c9b594824ff3da71d24647821991c9ab5d1f2f9870fd9a07cb2341ba4"
OFFICIAL_EXE = "49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"
V1_EXE = "2609c2687dd2ffb3f32c7687ed04f57b38ef6879c14b1c546faf8bfd8f35ea6b"   # iw4x.exe of an IW4x-32 v1.x install
MANIFEST = os.environ.get("IW4X32_UPDATE_URL") or f"https://github.com/{REPO}/releases/latest/download/latest.json"
LAUNCHER_RELEASE = os.environ.get("IW4X32_LAUNCHER_RELEASE_URL") or "https://api.github.com/repos/iw4x/launcher/releases/latest"
LAUNCH_OPTION = """bash -c 'exec "${@/iw4mp.exe/iw4x.exe}"' -- %command%"""
MW2 = "Call of Duty Modern Warfare 2"
FILES = os.path.dirname(os.path.abspath(__file__))        # <kit>/files: the program, backup/ and mode.txt
KIT = os.path.dirname(FILES)                              # the IW4x-32 folder
GAME = None
MODES = ["iw4x32", "vanilla", "server", "vanilla-server", "uninstall", "fix"]
REMOTE_EVERY = 15 * 60        # s between the official launcher's online checks (GitHub: 60 requests an hour)
# what IW4x-32 v1.x, v2.0 and the v2.1 test builds had in the IW4x-32 folder; everything is IW4x-32.sh + files/ now
LEGACY = ["AI_CREDITS.txt", "CHANGES.txt", "SHA256SUMS.txt", "IW4x-32 Launcher.bat", "IW4x-32 Setup.bat",
          "Install IW4x-32.bat", "Play IW4x-32 (IW4x launcher, no file check).bat", "Play IW4x-32 (no update).bat",
          "Play IW4x-32.bat", "Start IW4x-32 Server.bat", "Uninstall IW4x-32.bat", "install-linux.sh",
          "iw4x32_update.ps1", "iw4x32_update.py", "launcher-linux.sh", "play-linux.sh", "setup-linux.sh",
          "start-server-linux.sh", "uninstall-linux.sh", "server/server_iw4x32.cfg", "server/server_vanilla.cfg",
          "latest.json", "files/iw4x.exe"]                                   # the last two: v1.x kits
LEGACY_DIRS = ["source"]                                                    # v1.x: the patch manifests
DESKTOP = ["iw4x32.desktop", "iw4x32-server.desktop", "iw4x32-vanilla.desktop",
           "iw4x32-play.desktop", "iw4x32-vanilla-server.desktop"]    # the last two: made by the v2.1 test builds


class Opts:
    mode = None
    port = "28960"
    dry = False
    no_update = os.environ.get("IW4X32_NO_UPDATE") == "1"
    direct = False
    setup = False
    setup_path = None
    game_args = []
    warned = False
    detached = False


O = Opts()


def parse(argv):
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--play", "--iw4x32"):
            O.mode = "iw4x32"
        elif a in ("--vanilla", "--server", "--vanilla-server", "--uninstall", "--fix"):
            O.mode = a[2:]
        elif a == "--setup":
            O.setup = True
            if i + 1 < len(argv) and not argv[i + 1].startswith(("-", "+")):
                i += 1
                O.setup_path = argv[i]
        elif a == "--no-update":
            O.no_update = True
        elif a in ("--dry", "--dry-run"):
            O.dry = True
        elif a == "--direct":
            O.direct = True
        elif a == "--migrate":
            pass                           # an IW4x-32 v2.0 script forwarded here (iw4x32_update.py)
        elif a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif a.isdigit() and O.mode in ("server", "vanilla-server"):
            O.port = a
        else:
            O.game_args.append(a)
        i += 1


def say(msg):
    print(f"[IW4x-32] {msg}", flush=True)


def warn(msg):
    O.warned = True
    print(f"[IW4x-32] WARNING: {msg}", flush=True)


def F(name):
    return os.path.join(FILES, *name.split("/"))


def G(name):
    return os.path.join(GAME, name)


def sha(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except (OSError, TypeError):
        return None


def get(url, timeout=5):        # 5 s: a version check must never hold up a game start
    req = urllib.request.Request(url, headers={"User-Agent": "iw4x32-updater", "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def kver(v):
    """an IW4x-32 version's order: vMAJOR.MINOR only - the -rNNNN (v2.6-r5278) names the IW4x it is built for"""
    m = re.match(r"v(\d+)\.(\d+)", v or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def interactive():
    return sys.stdin.isatty()


def wait_close():
    if interactive():
        try:
            input("Press Enter to close")
        except EOFError:
            pass


def is_game(d):
    return bool(d) and os.path.isdir(d) and any(os.path.isfile(os.path.join(d, e)) for e in ("iw4mp.exe", "iw4x.exe", "iw2mp.exe"))


def installed_version(kit=None):
    try:
        m = re.match(r"IW4x-32 (v[\d.]+(?:-r\d+)?)", open(os.path.join(kit or KIT, "README.txt"), encoding="utf-8", errors="replace").readline())
        return m.group(1) if m else "v0"
    except OSError:
        return "v0"


def state():
    """files/state.json: when the official launcher last checked online"""
    try:
        return json.load(open(F("state.json")))
    except (OSError, ValueError):
        return {}


def save_state(**kv):
    s = state()
    s.update(kv)
    try:
        json.dump(s, open(F("state.json"), "w"))
    except OSError:
        pass


_DLL = {}


def dll_info(p):
    """(the IW4x release an iw4x.dll is, whether it is IW4x-32's): both are in its strings ("IW4x r5278", "iw4x32");
    (None, False) for no file / no version in it"""
    try:
        st = os.stat(p)
    except (OSError, TypeError):
        return None, False
    key = (p, st.st_size, st.st_mtime_ns)
    if key not in _DLL:
        data = open(p, "rb").read()
        m = re.search(rb"IW4x \(?(r\d{4,})", data)
        _DLL[key] = (m.group(1).decode() if m else None, re.search(rb"(?i)iw4x32", data) is not None)
    return _DLL[key]


def built_for():
    """x: the IW4x release this IW4x-32's iw4x.dll is built on"""
    return dll_info(F("iw4x.dll"))[0] or OFFICIAL_VER


def official_dll():
    """the official IW4x iw4x.dll: the one in the game folder, or its backup while IW4x-32's is in"""
    return F("backup/iw4x.dll") if dll_info(G("iw4x.dll"))[1] else G("iw4x.dll")


def iw4x_version():
    """y: the official IW4x release installed in the game folder (None = unknown)"""
    p = official_dll()
    return dll_info(p)[0] or (OFFICIAL_VER if sha(p) == OFFICIAL_DLL else None)


def version_status():
    x, y = built_for(), iw4x_version()
    if not y:
        return f"IW4x-32 is built for IW4x {x} - the version of your IW4x is unknown"
    if y == x:
        return f"IW4x-32 is built for IW4x {x}, your IW4x is {y} - they match"
    return (f"IW4x-32 is built for IW4x {x}, your IW4x is {y} ({'newer' if vtuple(y) > vtuple(x) else 'older'}) - "
            f"vanilla IW4x runs {y}, IW4x-32 runs its own {x} build")


def game_running():
    """only THIS game folder's iw4x.exe counts (a dedicated server elsewhere does not)"""
    r = subprocess.run(["pgrep", "-x", "iw4x.exe"], capture_output=True, text=True)
    for pid in r.stdout.split():
        try:
            if os.path.realpath(f"/proc/{pid}/cwd") == os.path.realpath(GAME):
                return True
        except OSError:
            pass
    return False


def backup_dll():
    """the official iw4x.dll in the game folder becomes the backup (never an IW4x-32 one, e.g. an older release's)"""
    if dll_info(G("iw4x.dll"))[1]:
        return
    os.makedirs(F("backup"), exist_ok=True)
    shutil.copy2(G("iw4x.dll"), F("backup/iw4x.dll"))


def install_ours():
    tmp = G("iw4x.dll.iw4x32-new")
    shutil.copy2(F("iw4x.dll"), tmp)
    os.replace(tmp, G("iw4x.dll"))
    if sha(G("iw4x.dll")) != sha(F("iw4x.dll")):
        raise RuntimeError("installing iw4x.dll failed")


def restore_v1_exe(official_exe):
    """an IW4x-32 v1.x install put its own iw4x.exe in the game folder; v2 runs the official IW4x one
    (official_exe = None: any backup made by an installer is good enough)"""
    if sha(G("iw4x.exe")) != V1_EXE:
        return
    bak = sha(F("backup/iw4x.exe"))
    if not bak or (official_exe and bak != official_exe):
        say("an older IW4x-32 replaced your iw4x.exe and there is no backup of it - the official IW4x launcher repairs it")
        install_official()
        return
    say("an older IW4x-32 replaced iw4x.exe - putting your official one back")
    shutil.copy2(F("backup/iw4x.exe"), G("iw4x.exe"))


# ---- the official IW4x launcher: it installs and updates IW4x itself --------------------------------------------
def ensure_launcher():
    for name in ("iw4x-launcher", "iw4x-launcher.exe", "iw4x-launcher-x86.exe"):
        if os.path.exists(G(name)):
            return G(name)
    try:
        rel = json.loads(get(LAUNCHER_RELEASE))
        asset = next(a for a in rel["assets"] if a["name"].endswith("-x86_64-linux-glibc.tar.xz"))
        data = get(asset["browser_download_url"], timeout=120)
    except Exception as e:
        say(f"the official IW4x launcher is not in the game folder and could not be downloaded ({type(e).__name__})")
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
    tmp = G("iw4x-launcher.iw4x32-new")
    open(tmp, "wb").write(body)
    os.chmod(tmp, 0o755)
    os.replace(tmp, G("iw4x-launcher"))
    say(f"downloaded the official IW4x launcher {rel.get('tag_name', '')}")
    return G("iw4x-launcher")


def remote_due():
    return time.time() - float(state().get("launcher_remote_at") or 0) > REMOTE_EVERY


def run_launcher(args, remote=True):
    """the official IW4x launcher; remote=False: --skip-remote (no GitHub, no file check). The official iw4x.dll goes
    back in first - its file check finds IW4x-32's and downloads the official one again otherwise."""
    launcher = ensure_launcher()
    if not launcher:
        return None
    put_official_dll()
    cmd = [launcher] + list(args) + ([] if remote else ["--skip-remote"])
    if launcher.endswith(".exe"):
        cmd = ["wine"] + cmd
    if remote:
        save_state(launcher_remote_at=time.time())
    return subprocess.run(cmd, cwd=GAME)


def install_official():
    say("the official IW4x launcher installs / updates IW4x (this can take a few minutes the first time) ...")
    return run_launcher(["--skip-launch"]) is not None


def put_official_dll():
    if dll_info(G("iw4x.dll"))[1] and sha(F("backup/iw4x.dll")):
        tmp = G("iw4x.dll.iw4x32-off")
        shutil.copy2(F("backup/iw4x.dll"), tmp)
        os.replace(tmp, G("iw4x.dll"))
        return True
    return False


def restore_official():
    """put the official IW4x iw4x.dll back - what vanilla IW4x and a vanilla server start from"""
    if put_official_dll():
        say("put the official IW4x iw4x.dll back")
    restore_v1_exe(None)


# ---- updates and repairs ------------------------------------------------------------------------------------------
def repair(m):
    """IW4x-32's iw4x.dll belongs in the game folder whenever IW4x-32 starts: the official IW4x launcher (vanilla, its
    file check) puts the official one back - a new official one becomes the backup. An IW4x older than the one
    IW4x-32 is built for is updated first; a newer one stays (vanilla runs it, IW4x-32 runs its own build)."""
    restore_v1_exe(((m or {}).get("official") or {}).get("iw4x.exe") or OFFICIAL_EXE)
    if not os.path.isfile(G("iw4x.dll")):
        say("iw4x.dll is missing - the official IW4x launcher repairs IW4x")
        install_official()
        if not os.path.isfile(G("iw4x.dll")):
            raise RuntimeError("IW4x is not installed in the game folder")
    ours = sha(F("iw4x.dll"))
    if sha(G("iw4x.dll")) != ours and not dll_info(G("iw4x.dll"))[1]:
        if sha(G("iw4x.dll")) == sha(F("backup/iw4x.dll")):
            say("the official IW4x iw4x.dll is back (IW4x launcher?) - putting IW4x-32 back")
        else:
            say(f"the official IW4x launcher installed IW4x {iw4x_version() or '(unknown version)'} - kept as your vanilla IW4x")
            backup_dll()
    update_iw4x()
    if sha(G("iw4x.dll")) != ours:
        install_ours()


def update_iw4x():
    """y older than x: the official IW4x launcher updates IW4x (at most every 15 min - it asks GitHub)"""
    x, y = built_for(), iw4x_version()
    if not y or vtuple(y) >= vtuple(x):
        return
    if not remote_due():
        say(f"your IW4x {y} is older than {x} (IW4x-32 is built for it) - the IW4x launcher tried less than 15 min ago")
        return
    say(f"your IW4x {y} is older than {x} (IW4x-32 is built for it) - the official IW4x launcher updates it ...")
    r = run_launcher(["--skip-launch"])
    if r is not None and os.path.isfile(G("iw4x.dll")):
        backup_dll()
    if vtuple(iw4x_version()) < vtuple(x):
        say(f"the IW4x launcher did not update IW4x (exit {getattr(r, 'returncode', '-')}) - start again later to retry")


def update_kit(m):
    """every file of the release whose SHA-256 differs: download all, check all, then swap them in"""
    skip = set(m.get("legacy") or [])
    todo = [p for p, h in m["files"].items() if p not in skip and sha(os.path.join(KIT, p)) != h]
    say(f"IW4x-32 {m['version']}: downloading {len(todo)} file(s) ...")
    os.makedirs(FILES, exist_ok=True)
    stage = tempfile.mkdtemp(prefix=".update-", dir=FILES)
    try:
        for p in todo:
            data = get(m["base_url"] + urllib.parse.quote(p), timeout=120)
            if hashlib.sha256(data).hexdigest() != m["files"][p]:
                raise RuntimeError(f"download check failed for {p} - nothing was changed")
            dst = os.path.join(stage, p)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(data)
        for p in todo:                                   # all verified: swap in (rename = safe for a running script)
            dst = os.path.join(KIT, p)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(os.path.join(stage, p), dst)
            os.chmod(dst, 0o755 if p.endswith((".sh", ".py")) else 0o644)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def do_update():
    """a new IW4x-32: every changed file downloaded and checked, then IW4x-32 is put (back) in"""
    have = installed_version()
    m = None
    if not O.no_update:
        try:
            m = json.loads(get(MANIFEST))
        except Exception as e:
            say(f"no update check ({type(e).__name__}) - starting IW4x-32 {have}")
    if m and kver(m["version"]) > kver(have) and game_running():
        say("the game is running - updating next time")
        m = None
    repair(m)
    if not m or kver(m["version"]) <= kver(have):
        return
    update_kit(m)
    repair(m)                                            # the new iw4x.dll in; an IW4x older than it is built for: updated
    migrate_legacy()
    say(f"updated to IW4x-32 {m['version']} (built for IW4x {built_for()})")


# ---- setup ----------------------------------------------------------------------------------------------------------
def steam_dirs():
    if os.environ.get("IW4X32_STEAM"):
        return [os.environ["IW4X32_STEAM"]]
    h = os.path.expanduser("~")
    return [d for d in (f"{h}/.steam/steam", f"{h}/.local/share/Steam", f"{h}/snap/steam/common/.local/share/Steam",
                        f"{h}/.var/app/com.valvesoftware.Steam/.local/share/Steam") if os.path.isdir(d)]


def steam_libraries():
    libs = []
    for d in steam_dirs():
        libs.append(d)
        try:
            vdf = open(os.path.join(d, "steamapps", "libraryfolders.vdf"), errors="replace").read()
            libs += [p.replace("\\\\", "\\") for p in re.findall(r'"(?:path|\d+)"\s+"([^"]+)"', vdf)]
        except OSError:
            pass
    out = []
    for p in libs:
        r = os.path.realpath(p)
        if r not in out:
            out.append(r)
    return out


def pick_game():
    found = []
    for lib in steam_libraries():
        for d in sorted(glob.glob(os.path.join(glob.escape(lib), "steamapps", "common", MW2 + "*"))):
            r = os.path.realpath(d)
            if is_game(r) and r not in found:
                found.append(r)
    if len(found) == 1:
        say(f"found Modern Warfare 2: {found[0]}")
        return found[0]
    if found:
        print("Modern Warfare 2 is installed in more than one place:")
        for n, d in enumerate(found, 1):
            print(f"  [{n}] {d}")
        a = (input("Which one? (Enter = 1) ") if interactive() else "").strip() or "1"
        return found[int(a) - 1] if a.isdigit() and 1 <= int(a) <= len(found) else None
    print("Modern Warfare 2 was not found in your Steam libraries.")
    print('  You need "Call of Duty: Modern Warfare 2" (2009) - the multiplayer part - from Steam.')
    if not interactive():
        return None
    a = input("Type your MW2 folder (the one with iw4mp.exe), S = open Steam to install MW2, Enter = stop: ").strip()
    if a.lower() == "s":
        subprocess.Popen(["xdg-open", "steam://install/10190"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Install it in Steam, then run ./IW4x-32.sh again.")
        return None
    return os.path.expanduser(a.strip("'\"")) or None


def copy_kit(dest):
    """the kit into <game>/IW4x-32 (an existing backup/ and mode.txt there are kept)"""
    say(f"copying IW4x-32 to {dest}")
    os.makedirs(os.path.join(dest, "files"), exist_ok=True)
    for n in ("IW4x-32.bat", "IW4x-32.sh", "README.txt"):
        if os.path.isfile(os.path.join(KIT, n)):
            shutil.copy2(os.path.join(KIT, n), os.path.join(dest, n))
    for n in os.listdir(FILES):
        if n in ("backup", "mode.txt", "state.json", "__pycache__") or n.startswith("."):
            continue
        s, t = os.path.join(FILES, n), os.path.join(dest, "files", n)
        if os.path.isdir(s):
            shutil.copytree(s, t, dirs_exist_ok=True)
        else:
            shutil.copy2(s, t)


def apps_dir():
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications")


def make_shortcuts():
    if os.environ.get("IW4X32_NO_SHORTCUTS") == "1":
        return
    sh = os.path.join(KIT, "IW4x-32.sh")
    try:
        os.makedirs(apps_dir(), exist_ok=True)
        for f, name, comment, arg in (("iw4x32.desktop", "IW4x-32", "Modern Warfare 2 with 32 players", ""),
                                      ("iw4x32-server.desktop", "IW4x-32 Server", "32-player dedicated server", " --server"),
                                      ("iw4x32-vanilla.desktop", "IW4x (vanilla)", "The official IW4x", " --vanilla")):
            with open(os.path.join(apps_dir(), f), "w") as out:
                out.write(f"[Desktop Entry]\nType=Application\nVersion=1.0\nName={name}\nComment={comment}\n"
                          f"Exec=sh {shlex.quote(sh)}{arg}\nPath={GAME}\nTerminal=true\nCategories=Game;\n")
        for f in DESKTOP[3:]:
            if os.path.exists(os.path.join(apps_dir(), f)):
                os.remove(os.path.join(apps_dir(), f))
        say("menu entries: IW4x-32, IW4x-32 Server, IW4x (vanilla) - in your applications menu (Games)")
    except OSError as e:
        say(f"could not make the menu entries ({e}) - start IW4x-32 with {sh}")


def remove_shortcuts():
    for f in DESKTOP:
        try:
            os.remove(os.path.join(apps_dir(), f))
        except OSError:
            pass


def steam_tip():
    if "/steamapps/common/" in GAME and not launch_option_set(steam_app()[0]):
        print("\nSteam tip (once): Modern Warfare 2 - Multiplayer -> Properties -> Launch Options:\n\n"
              f"    {LAUNCH_OPTION}\n\nthen the Play button in Steam starts IW4x-32 too.")


def install_here():
    """IW4x (official launcher) + IW4x-32 into GAME, then the menu entries"""
    say(f"setting up IW4x-32 in {GAME}")
    if game_running():
        say("ERROR: IW4x is running - close the game and try again")
        return False
    # the official launcher only when there is no official IW4x here (it asks GitHub and checks every file)
    if not os.path.isfile(G("iw4x.exe")) or not sha(official_dll()):
        install_official()
    restore_v1_exe(OFFICIAL_EXE)
    if not sha(official_dll()) or not os.path.isfile(G("iw4x.exe")):
        say("ERROR: IW4x could not be installed - is the internet working? Start IW4x-32 again to retry.")
        return False
    backup_dll()
    update_iw4x()
    if sha(G("iw4x.dll")) != sha(F("iw4x.dll")):
        install_ours()
    make_shortcuts()
    say("IW4x-32 is installed.")
    steam_tip()
    return True


def do_setup():
    global KIT, FILES, GAME
    g = O.setup_path or pick_game()
    if not g:
        say("nothing was changed")
        return False
    if not is_game(g):
        say(f"ERROR: no iw4mp.exe or iw4x.exe in {g} - nothing was changed")
        return False
    g = os.path.realpath(g)
    dest = os.path.join(g, "IW4x-32")
    if os.path.realpath(dest) != os.path.realpath(KIT):
        theirs, mine = installed_version(dest), installed_version()
        if os.path.isfile(os.path.join(dest, "files", "iw4x32.py")) and kver(theirs) >= kver(mine):
            # this game already has IW4x-32 (an update may have made it newer than this copy): start that one - a
            # setup from here would put this older copy over it, and the next update download it all again
            say(f"IW4x-32 {theirs} is already set up in {g} - starting that one (this copy, {KIT}, is not needed)")
            sys.stdout.flush()
            os.execv(sys.executable, [sys.executable, os.path.join(dest, "files", "iw4x32.py")] + sys.argv[1:])
        try:
            copy_kit(dest)
        except OSError as e:
            say(f"ERROR: could not copy to {dest} ({e}) - nothing else was changed")
            return False
        KIT, FILES = dest, os.path.join(dest, "files")
    GAME = g
    migrate_legacy()
    return install_here()


def migrate_legacy():
    """an IW4x-32 v2.0 folder: state into files/, the old scripts out (only when it really is one)"""
    if not any(os.path.exists(os.path.join(KIT, n)) for n in ("iw4x32_update.py", "play-linux.sh", "launcher-linux.sh",
                                                                "Play IW4x-32.bat")):
        return False
    for n in ("backup", "mode.txt"):
        old = os.path.join(KIT, n)
        if not os.path.exists(old):
            continue
        if os.path.exists(F(n)):
            shutil.rmtree(old) if os.path.isdir(old) else os.remove(old)
        else:
            os.replace(old, F(n))
    for n in LEGACY:
        try:
            os.remove(os.path.join(KIT, *n.split("/")))
        except OSError:
            pass
    for n in LEGACY_DIRS:
        shutil.rmtree(os.path.join(KIT, n), ignore_errors=True)
    try:
        os.rmdir(os.path.join(KIT, "server"))
    except OSError:
        pass
    say("tidied up the IW4x-32 folder - everything starts from IW4x-32.sh now")
    return True


# ---- what to start ----------------------------------------------------------------------------------------------------
def read_mode():
    try:
        w = open(F("mode.txt"), encoding="utf-8", errors="replace").read().split()
        return w[0] if w and w[0] in MODES[:4] else "iw4x32"
    except OSError:
        return "iw4x32"


def read_key(timeout, keys="\r\n123456"):
    """one key press (no Enter needed), '' after timeout s; a key that is no choice waits 30 s more"""
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        end = time.time() + timeout
        while True:
            if not select.select([sys.stdin], [], [], max(0, end - time.time()))[0]:
                return ""
            c = sys.stdin.read(1)
            if keys is None or c.lower() in keys:
                return c.lower()
            end = time.time() + 30
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def select_mode():
    default = read_mode()
    if os.environ.get("IW4X32_NO_MENU") == "1" or not interactive():
        return default
    d = MODES.index(default) + 1
    print(f"\n  IW4x-32 {installed_version()} - Modern Warfare 2 with 32 players\n  game: {GAME}")
    print(f"  {version_status()}\n")
    print("  [1] Play IW4x-32          32-player servers, and normal ones")
    print("  [2] Play vanilla IW4x     the official IW4x")
    print(f"  [3] Host a 32-player server   (port {O.port})")
    print(f"  [4] Host a normal IW4x server (port {O.port})")
    print("  [5] Uninstall IW4x-32")
    print("  [6] Game crashed / stuck?  closes what is left of it, so Steam can start it again\n")
    print(f"  Press 1-6 - or wait: [{d}] starts in 5 s ", end="", flush=True)
    try:
        c = read_key(5)
    except Exception:                                   # no real terminal: a line, then
        c = sys.stdin.readline().strip()[:1] if select.select([sys.stdin], [], [], 5)[0] else ""
    pick = int(c) if c in ("1", "2", "3", "4", "5", "6") else d
    print(pick)
    mode = MODES[pick - 1]
    if mode in MODES[:4]:
        try:
            open(F("mode.txt"), "w").write(mode + "\n")
        except OSError:
            pass
    return mode


# ---- start things -------------------------------------------------------------------------------------------------------
def run(cmd, **kw):
    print("  command: " + " ".join(shlex.quote(c) for c in cmd), flush=True)
    if O.dry or os.environ.get("IW4X32_NO_START") == "1":
        return 0
    return subprocess.call(cmd, **kw)


def steam_app():
    """(appid, compatdata folder) of this Steam library's MW2 multiplayer, (None, None) when there is none"""
    lib = GAME.split("/steamapps/common/")[0] + "/steamapps"
    for appid in ("10190", "10180"):
        if os.path.isdir(f"{lib}/compatdata/{appid}/pfx"):
            return appid, f"{lib}/compatdata/{appid}"
    return None, None


def launch_option_set(appid):
    for d in steam_dirs():
        for f in glob.glob(f"{glob.escape(d)}/userdata/*/config/localconfig.vdf"):
            t = open(f, errors="replace").read()
            for m in re.finditer(r'"%s"\s*\{' % (appid or "10190"), t):
                depth, i = 1, m.end()
                while i < len(t) and depth:
                    depth += {"{": 1, "}": -1}.get(t[i], 0)
                    i += 1
                lo = re.search(r'"LaunchOptions"\s*"((?:[^"\\]|\\.)*)"', t[m.end():i])
                if lo and "iw4x.exe" in lo.group(1):
                    return True
    return False


# ---- after a crash: what is left of the game keeps Steam saying "running" ---------------------------------------------
def is_game_exe(name):
    return name.lower().startswith(("iw4x.exe", "iw4x (mm)", "iw4mp.exe"))


def leftovers():
    """[(pid, name)] of this game's processes: the game, its crash reporter, wineserver, Proton's container and Steam's
    reaper - all carry MW2's AppId or Proton prefix (environment, or the reaper's command line), or run in this game
    folder. Never a dedicated server, never Steam itself, never this launcher."""
    appid, compat = steam_app() if GAME and "/steamapps/common/" in GAME else (None, None)
    ids = {"10190", appid or "10190"}
    envs = {f"{k}={i}".encode() for k in ("SteamAppId", "SteamGameId") for i in ids}
    if compat:
        envs.add(f"STEAM_COMPAT_DATA_PATH={compat}".encode())
    skip, p = set(), os.getpid()
    while p > 1 and p not in skip:                       # this launcher and what started it
        skip.add(p)
        try:
            p = int(open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    game = os.path.realpath(GAME) if GAME else None
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in skip:
            continue
        try:
            if os.stat(f"/proc/{d}").st_uid != os.getuid():
                continue
            name = open(f"/proc/{d}/comm").read().strip()
            cmd = open(f"/proc/{d}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
            env = set(open(f"/proc/{d}/environ", "rb").read().split(b"\0"))
            here = game and os.path.realpath(f"/proc/{d}/cwd") == game
        except OSError:
            continue
        if not cmd or "-dedicated" in cmd or name in ("steam", "steamwebhelper"):
            continue
        if env & envs or re.search(r"\bAppId=(%s)\b" % "|".join(ids), cmd) or (here and name.lower().endswith((".exe", ".ex"))):
            out.append((int(d), name))
    return out


def kill_procs(procs):
    say("closing what is left of the game (" + ", ".join(sorted({n for _, n in procs})) + ") so Steam can start it again")
    for sig, wait in ((signal.SIGTERM, 4), (signal.SIGKILL, 2)):
        for pid, _ in procs:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        end = time.time() + wait
        while time.time() < end and any(os.path.exists(f"/proc/{pid}") for pid, _ in procs):
            time.sleep(0.2)
        procs = [(pid, n) for pid, n in procs if os.path.exists(f"/proc/{pid}")]
        if not procs:
            return True
    say("could not close: " + ", ".join(f"{n} (pid {pid})" for pid, n in procs))
    return False


def clear_leftovers():
    """before a start: leftovers of a crash are closed; a game that still runs (or hangs) only after a yes.
    False = it keeps running."""
    procs = leftovers()
    if not procs:
        return True
    if any(is_game_exe(n) for _, n in procs):
        if not interactive():
            say("IW4x is already running - not starting it twice (./IW4x-32.sh --fix closes it)")
            return False
        try:
            a = input("[IW4x-32] IW4x is still running - hung after a crash? Close it and start again? [Y/n] ")
        except EOFError:
            a = "n"
        if a.strip().lower().startswith("n"):
            return False
    return kill_procs(procs)


def do_fix():
    procs = leftovers()
    if not procs:
        say("nothing of the game is running - Steam can start it")
        return 0
    return 0 if kill_procs(procs) else 1


def play(start):
    """start(); when the game closes - a crash too - what is left of it is closed and [R] starts it again, so a crash
    never needs a Steam restart"""
    while True:
        if not clear_leftovers():
            return 0
        O.detached = False
        rc = start()
        if O.dry or os.environ.get("IW4X32_NO_START") == "1" or not interactive():
            return rc
        if O.detached:                                   # Steam / the IW4x launcher started it: wait for the game
            end = time.time() + 90
            while time.time() < end and not any(is_game_exe(n) for _, n in leftovers()):
                time.sleep(2)
        if any(is_game_exe(n) for _, n in leftovers()):
            say("the game is running - this window can stay open: when it closes or crashes, [R] starts it again")
            while any(is_game_exe(n) for _, n in leftovers()):
                time.sleep(2)
        time.sleep(2)                                    # crash reporter, wineserver, reaper: give them a moment
        procs = leftovers()
        if procs:
            kill_procs(procs)
        print("\n  IW4x closed.  [R] start it again  -  any other key, or wait 30 s: close this window ", end="", flush=True)
        try:
            c = read_key(30, None)
        except Exception:
            c = ""
        print()
        if c != "r":
            return 0                                     # seen and answered: no "Press Enter to close" on top


def start_game():
    """what the official IW4x launcher does, minus its file check: without steam_appid.txt / SteamAppId Steam takes
    over and starts normal MW2"""
    if not os.path.isfile(G("iw4x.exe")):
        say(f"ERROR: no iw4x.exe in {GAME} - run ./IW4x-32.sh --setup")
        return 1
    if not O.dry and not os.path.isfile(G("steam_appid.txt")):
        open(G("steam_appid.txt"), "w", newline="").write("10190\r\n")
    if "/steamapps/common/" not in GAME:                         # not a Steam library: plain Wine
        if not shutil.which("wine"):
            say("ERROR: wine is not installed (Debian/Ubuntu: sudo apt install wine)")
            return 1
        say("starting IW4x-32 with Wine" + (f" (prefix {os.environ['WINEPREFIX']})" if os.environ.get("WINEPREFIX") else ""))
        return run(["wine", "iw4x.exe"] + O.game_args, cwd=GAME, env=dict(os.environ, SteamAppId="10190", SteamGameId="10190"))
    appid, compat = steam_app()
    if not compat:
        say("Steam has not made MW2's Proton files yet: start 'Modern Warfare 2 - Multiplayer' once from Steam, "
            "close it, then start IW4x-32 again")
        return 1
    if not O.direct and launch_option_set(appid):
        say("starting IW4x-32 through Steam (launch option found)")
        O.detached = True
        if shutil.which("steam"):
            return run(["steam", "-applaunch", appid] + O.game_args)
        return run(["xdg-open", f"steam://rungameid/{appid}"])
    info = open(f"{compat}/config_info", errors="replace").read().splitlines() if os.path.isfile(f"{compat}/config_info") else []
    proton = next((re.sub(r"/(files|dist)/share/fonts/?$", "", l) for l in info if re.search(r"/share/fonts/?$", l)), "")
    if not os.access(f"{proton}/proton", os.X_OK):
        say("could not find this game's Proton - set the Steam launch option instead:")
        print(f"\n    {LAUNCH_OPTION}\n")
        return 1
    steam = steam_dirs()[0] if steam_dirs() else proton.split("/steamapps/common/")[0]
    say(f"starting IW4x-32 with {info[0] if info else 'Proton'} in the game's own prefix")
    env = dict(os.environ, STEAM_COMPAT_DATA_PATH=compat, STEAM_COMPAT_CLIENT_INSTALL_PATH=steam,
               SteamAppId=appid, SteamGameId=appid)
    return run([f"{proton}/proton", "run", G("iw4x.exe")] + O.game_args, cwd=GAME, env=env)


def start_server(slots, cfg, label):
    if not os.path.isfile(G("iw4x.exe")):
        say(f"ERROR: no iw4x.exe in {GAME} - run ./IW4x-32.sh --setup")
        return 1
    if slots == 32 and sha(G("iw4x.dll")) != sha(F("iw4x.dll")):
        say("ERROR: IW4x-32 is not installed - run ./IW4x-32.sh --setup")
        return 1
    user = G("userraw")
    if not O.dry and not os.path.isfile(os.path.join(user, cfg)):
        os.makedirs(user, exist_ok=True)
        shutil.copy2(F(cfg), os.path.join(user, cfg))
        say(f"made userraw/{cfg} - set your server name and an rcon password there, then restart the server")
    sa = ["-dedicated", "-stdout", "+set", "net_port", O.port, "+exec", cfg, "+set", "sv_maxclients", str(slots),
          "+set", "party_maxplayers", str(slots), "+set", "party_enable", "0", "+map_rotate"]
    print(label)
    print(f"  game folder: {GAME}")
    print(f"  settings:    {os.path.join(user, cfg)}")
    print(f"  port:        {O.port} UDP - forward it on your router for players on the internet")
    print("  bots:        type  spawnBot 10  in the server console")
    if not O.dry and os.environ.get("IW4X32_NO_START") != "1" and not shutil.which("wine"):
        say("ERROR: wine is not installed (Debian/Ubuntu: sudo apt install wine)")
        return 1
    env = dict(os.environ, WINEPREFIX=os.environ.get("WINEPREFIX") or os.path.expanduser("~/.wine-iw4x32-server"),
               WINEDEBUG="-all")
    rc = run(["wine", "iw4x.exe"] + sa, cwd=GAME, env=env)
    if not O.dry and os.environ.get("IW4X32_NO_START") != "1":
        say("the server stopped")
    return rc


def do_uninstall():
    if os.environ.get("IW4X32_YES") != "1":
        if not interactive():
            say("uninstall needs a yes: IW4X32_YES=1")
            return 1
        if not input("Uninstall IW4x-32 and put the official IW4x files back? [y/N] ").strip().lower().startswith("y"):
            say("nothing was changed")
            return 0
    if game_running():
        say("ERROR: close the game first")
        return 1
    if os.path.isfile(F("backup/iw4x.dll")):
        shutil.copy2(F("backup/iw4x.dll"), G("iw4x.dll"))
        restore_v1_exe(None)
        say("the official IW4x files are back")
    else:
        say("no backup of the official iw4x.dll - the official IW4x launcher repairs it")
        install_official()
    remove_shortcuts()
    say(f"IW4x-32 is uninstalled. You can delete the folder {KIT}")
    return 0


def main():
    global GAME
    parse(sys.argv[1:])
    if not os.path.isfile(F("iw4x.dll")):
        # only IW4x-32.sh was downloaded (or the zip was not fully extracted): get the rest of the release
        say("getting IW4x-32 from GitHub ...")
        update_kit(json.loads(get(MANIFEST, timeout=30)))
    migrated = migrate_legacy()
    GAME = os.environ.get("IW4X32_GAME") or (os.path.dirname(KIT) if is_game(os.path.dirname(KIT)) else None)
    if O.setup or not GAME:
        if not do_setup():
            return 1
        if O.setup and not O.mode:
            return 0
    elif not os.path.isfile(F("backup/iw4x.dll")) and sha(G("iw4x.dll")) != sha(F("iw4x.dll")):
        if not install_here():                    # the kit is in the game folder but was never installed
            return 1
    elif migrated:
        make_shortcuts()
    if O.mode == "fix":
        return do_fix()
    mode = O.mode or select_mode()
    while mode == "fix":                                 # [6] in the menu: clean up, then the menu again
        do_fix()
        mode = select_mode()
    O.mode = mode
    if mode == "vanilla":
        restore_official()
        if O.dry or os.environ.get("IW4X32_NO_START") == "1":
            say("starting vanilla IW4x " + (iw4x_version() or ""))
            return 0

        def vanilla():
            remote = remote_due()
            say(f"starting vanilla IW4x {iw4x_version() or ''} (the official IW4x launcher"
                + (" updates it first) ..." if remote else ", no online check - it checked less than 15 min ago) ..."))
            t0 = time.time()
            r = run_launcher([], remote)
            O.detached = time.time() - t0 < 20          # it started the game and did not wait for it
            return 0 if r is not None else 1
        return play(vanilla)
    if mode == "vanilla-server":
        if not O.dry:
            restore_official()
        return start_server(18, "server_vanilla.cfg", "IW4x server - vanilla, 18 players")
    if mode == "uninstall":
        return do_uninstall()
    if not O.dry:
        do_update()
    if mode == "server":
        return start_server(32, "server_iw4x32.cfg", "IW4x-32 server - 32 players")
    say(version_status())
    return play(start_game)


if __name__ == "__main__":
    try:
        rc = main()
    except KeyboardInterrupt:
        rc = 130
    except Exception as e:
        say(f"ERROR: {e}")
        rc = 1
        if GAME and O.mode in (None, "iw4x32"):
            say("starting the game anyway")
            try:
                rc = start_game()
            except Exception:
                pass
    if O.warned and interactive():
        time.sleep(5)                                   # let a warning be read before a terminal window closes
    if rc and interactive():
        wait_close()
    sys.exit(rc)
