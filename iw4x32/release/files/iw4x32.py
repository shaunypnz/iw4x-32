#!/usr/bin/env python3
"""IW4x-32 for Linux / Steam Deck - setup, start menu, auto-update, play, host a server, uninstall: all of it is
this file. IW4x-32.sh runs it. Windows: iw4x32.ps1 next to it does the same steps.

  ./IW4x-32.sh                          first time: sets everything up; then the start menu
  ./IW4x-32.sh --play                   IW4x-32 (IW4x-32 servers up to 96 players, and normal ones)
  ./IW4x-32.sh --native                 IW4x-32 in a native Linux process (Vulkan, no Wine / Proton) - same servers
  ./IW4x-32.sh --wine                   IW4x-32 the classic way: Steam's Proton, or Wine outside Steam
  ./IW4x-32.sh --native-server [port]   96-player dedicated server, native (no Wine)
  ./IW4x-32.sh --vanilla                vanilla IW4x (the official IW4x launcher updates and starts it)
  ./IW4x-32.sh --server [port]          96-player dedicated server (port 28960; Wine, or native with --native)
  ./IW4x-32.sh --vanilla-server [port]  normal 18-player IW4x server
  ./IW4x-32.sh --setup [game folder]    do the setup again, e.g. for another game folder
  ./IW4x-32.sh --uninstall              put the official IW4x files back, remove the menu entries
  ./IW4x-32.sh --fix                    the game crashed / hangs and Steam will not start it: close what is left
  --no-update  skip the update check     --dry  only print what would be started
  --self-test  check this launcher's own logic - both runtimes, the native machine checks, updates; starts no game
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
IW4X32_NO_START=1 (print the command, start nothing), IW4X32_NO_SHORTCUTS=1, IW4X32_YES=1 (uninstall without asking),
IW4X32_NATIVE=<path to iw4x-native> (a loader outside the kit - private / test kits), IW4X32_NO_NATIVE=1 (hide the
native run), IW4X32_NO_CHECKS=1 (skip the native machine checks: the loader's own error answers instead),
IW4X32_DESKTOP_DIR=<dir> (where the menu entries go).

How to run (the runtime): "iw4x32" starts the real IW4x client - official iw4x.exe + our iw4x.dll - either under
Steam's Proton / Wine ("wine") or natively, in a 32-bit Linux process with DXVK-native on Vulkan, no Wine and no DX9
("native"). Same client, same protocol: a native player, a Wine/Proton player and a Windows player join the same
IW4x server. The native run exists only when the kit has files/iw4x-native (private builds till the owner promotes
it), so --native there is refused. files/runtime.txt remembers the last choice; --native / --wine pick it for THIS
start only."""
import base64, glob, hashlib, io, json, os, re, select, shlex, shutil, signal, subprocess, sys, tarfile, tempfile, time
import urllib.parse, urllib.request

REPO = "shaunypnz/iw4x-32"
OFFICIAL_VER = "r5318"
# IW4x-32: the player count files/iw4x.dll is built for (Game::MAX_CLIENTS) - what "host" runs
PLAYERS = 96
# IW4x-32: the native Linux (Vulkan) loader. Promoting it is ONE switch in the release file set: a release that
# lists files/iw4x-native ships the loader (the update check brings it into every kit), and that is what makes the
# menu offer the native run - the public kit does not list it, so the option stays hidden there. NATIVE_DEFAULT
# then makes it the default run: only once phase f passed on the test box, the mixed native + Wine/Proton join
# passed here and the owner said go (owner 2026-10-23: private builds only until then).
NATIVE_FILE = "iw4x-native"                                        # under files/, like every other program file
NATIVE_DEFAULT = False
RUNTIMES = ["native", "wine"]
# what a native run needs that a 64-bit desktop does not have by itself: the i386 runtime (the loader is a 32-bit
# process) and the i386 Vulkan loader that DXVK-native opens. Debian/Ubuntu names - Steam Deck ships them.
I386_PKGS = {"libc.so.6": "libc6:i386", "libm.so.6": "libc6:i386", "libdl.so.2": "libc6:i386",
             "libpthread.so.0": "libc6:i386", "librt.so.1": "libc6:i386", "libnsl.so.1": "libnsl2:i386",
             "libgcc_s.so.1": "libgcc-s1:i386", "libstdc++.so.6": "libstdc++6:i386",
             "libSDL2-2.0.so.0": "libsdl2-2.0-0:i386", "libvulkan.so.1": "libvulkan1:i386",
             "libasound.so.2": "libasound2:i386", "libpulse.so.0": "libpulse0:i386",
             "libX11.so.6": "libx11-6:i386", "libXext.so.6": "libxext6:i386", "libdrm.so.2": "libdrm2:i386",
             "libwayland-client.so.0": "libwayland-client0:i386", "libxkbcommon.so.0": "libxkbcommon0:i386"}
I386_OTHER = "(rpm: glibc.i686, libstdc++.i686, SDL2.i686, vulkan-loader.i686)"
VK_PKGS = {"amd": "mesa-vulkan-drivers (Radeon / RADV)", "intel": "mesa-vulkan-drivers (ANV)",
           "nvidia": "the nvidia driver package your card needs (it ships its own Vulkan ICD)"}
OFFICIAL_DLL = "d9f1440a6e17f397b1eb8a7d770d1be8043b9ea276b9c8775a4677cdaa10615d"
OFFICIAL_EXE = "49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"
V1_EXE = "2609c2687dd2ffb3f32c7687ed04f57b38ef6879c14b1c546faf8bfd8f35ea6b"   # iw4x.exe of an IW4x-32 v1.x install
# the IW4x-32 release key (RSA-3072, "modulus:exponent" in hex): an update is taken only from a latest.json signed
# with it (latest.json.sig next to it) - a release that is not signed by the owner's key never reaches this PC
RELEASE_KEY = (
    "b3d1e635d2cbb05774f8f9e016a111bd6f3fc2ef1d2c0010d63003ffb503b5a43bfa5e104a3b039135bb9ca8cf15a18d"
    "0375798e2c246c884c9319c9328463600382e8eab31886ff59f1d2e0ec8eeaad642cf0f46b625b36bc4571c05f050180"
    "f0ba99310892eb4e4bb6d5e6770b6be91d69be07bfefd598381a6a8cf9e84a5be9f94bfdbbb4dbd55f9bc8ea485630b7"
    "de40db5b53df40efb3970f57f2fec67ec4be2a346306a1ef02f0b4db4a22babe70ac14271c152c37a2414c148d821a37"
    "d96d2bba03dcab4e79bd976b664b3875c38ecaa29bd0d173f73a86e2937722e4635cbccac33821da93158ced0069d431"
    "ee291697ccaee886f5afa8cf967e4f7efba9b65e25d9cad1bf377053a8f94ab9a5c1a3850307c6544bf50a5cedfab8a4"
    "a1195926d8e13813457d590db39cca1599c622054b8fd99d576bcda8c36a31ff21970d43464923913da2082c37b669f8"
    "483862b64fc68354e4883543c3e40757284a2912d92502fa2db1384eb192b925039a14a9ff3742537b7e94a333a307fb"
    ":10001")
MANIFEST = os.environ.get("IW4X32_UPDATE_URL") or f"https://github.com/{REPO}/releases/latest/download/latest.json"
if os.environ.get("IW4X32_TEST_RELEASE_KEY") and MANIFEST.startswith("http://127.0.0.1:"):
    RELEASE_KEY = os.environ["IW4X32_TEST_RELEASE_KEY"]  # kit_test.sh's own key, for its fake GitHub on localhost only
LAUNCHER_RELEASE = os.environ.get("IW4X32_LAUNCHER_RELEASE_URL") or "https://api.github.com/repos/iw4x/launcher/releases/latest"
LAUNCH_OPTION = """bash -c 'exec "${@/iw4mp.exe/iw4x.exe}"' -- %command%"""
MW2 = "Call of Duty Modern Warfare 2"
FILES = os.path.dirname(os.path.abspath(__file__))        # <kit>/files: the program, backup/ and mode.txt
KIT = os.path.dirname(FILES)                              # the IW4x-32 folder
GAME = None
MODES = ["iw4x32", "iw4x32", "vanilla", "server", "vanilla-server", "uninstall", "fix"]
# IW4x-32: [0] is the native run, [1] the Wine/Proton one - the same "iw4x32" mode, so an older kit's mode.txt and
# menu entries keep working. Which of the two the number keys mean follows the player's last choice.
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
           "iw4x32-play.desktop", "iw4x32-vanilla-server.desktop", "iw4x32-native.desktop",
           "iw4x32-native-server.desktop"]    # the last three: made by the v2.1 test builds; the native pair is new


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
    runtime = None                       # this start only: native | wine (files/runtime.txt is the standing choice)


O = Opts()


def parse(argv):
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--self-test":
            sys.exit(self_test())        # the launcher's own logic: no game, no network, nothing installed
        if a in ("--native", "--iw4x32-native"):
            O.mode, O.runtime = "iw4x32", "native"
        elif a in ("--wine", "--proton", "--iw4x32-wine"):
            O.mode, O.runtime = "iw4x32", "wine"
        elif a == "--native-server":
            O.mode, O.runtime = "server", "native"
        elif a in ("--play", "--iw4x32"):
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


class Unsigned(Exception):
    """latest.json without a valid signature from the release key"""


def signed(data, sig):
    """RSA PKCS#1 v1.5 SHA-256 over data with RELEASE_KEY (the same check as the release pipeline's)"""
    n_hex, e_hex = RELEASE_KEY.split(":")
    n, e = int(n_hex, 16), int(e_hex, 16)
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    t = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(data).digest()
    return em == b"\x00\x01" + b"\xff" * (k - 3 - len(t)) + b"\x00" + t


def get_manifest(timeout=5):
    """latest.json - only when latest.json.sig proves the release key signed exactly these bytes"""
    data = get(MANIFEST, timeout)
    try:
        sig = base64.b64decode(get(MANIFEST + ".sig", timeout).strip(), validate=True)
    except Exception as e:
        raise Unsigned(f"no signature for latest.json ({type(e).__name__})")
    if not signed(data, sig):
        raise Unsigned("latest.json is not signed by the IW4x-32 release key")
    return json.loads(data)


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
            # IW4x-32: the executable bit is part of the file: the scripts AND the native loader (files/iw4x-native)
            # come back runnable, or a native kit updates itself into a kit that cannot start anything.
            os.chmod(dst, 0o755 if p.endswith((".sh", ".py")) or p == "files/" + NATIVE_FILE else 0o644)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def do_update():
    """a new IW4x-32: every changed file downloaded and checked, then IW4x-32 is put (back) in"""
    have = installed_version()
    m = None
    if not O.no_update:
        try:
            m = get_manifest()
        except Unsigned as e:
            say(f"update refused: {e} - starting IW4x-32 {have} as it is")
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
    d = os.environ.get("IW4X32_DESKTOP_DIR")                       # kit_test.sh / the native kit tests keep it local
    if d:
        return d
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications")


def shortcut_entries():
    """one app-menu entry per way to run: the default one, the Wine/Proton one, and - when this kit carries the
    loader - the native Linux one and its server. Same options the menu and the command line take."""
    out = [("iw4x32.desktop", "IW4x-32", f"Modern Warfare 2 with up to {PLAYERS} players", ""),
           ("iw4x32-wine.desktop", "IW4x-32 (Wine/Proton)", "the same client under Steam's Proton or Wine", " --wine"),
           ("iw4x32-server.desktop", "IW4x-32 Server", f"{PLAYERS}-player dedicated server (Wine/Proton)", " --server"),
           ("iw4x32-vanilla.desktop", "IW4x (vanilla)", "The official IW4x", " --vanilla")]
    if native_available():
        out.insert(1, ("iw4x32-native.desktop", "IW4x-32 (native Linux)",
                       "the real IW4x client on Vulkan, no Wine", " --native"))
        out.append(("iw4x32-native-server.desktop", "IW4x-32 Server (native Linux)",
                    f"{PLAYERS}-player dedicated server, no Wine", " --native-server"))
    return out


def make_shortcuts():
    if os.environ.get("IW4X32_NO_SHORTCUTS") == "1":
        return
    sh = os.path.join(KIT, "IW4x-32.sh")
    try:
        os.makedirs(apps_dir(), exist_ok=True)
        keep = set()
        for f, name, comment, arg in shortcut_entries():
            keep.add(f)
            with open(os.path.join(apps_dir(), f), "w") as out:
                out.write(f"[Desktop Entry]\nType=Application\nVersion=1.0\nName={name}\nComment={comment}\n"
                          f"Exec=sh {shlex.quote(sh)}{arg}\nPath={GAME}\nTerminal=true\nCategories=Game;\n")
        for f in DESKTOP:                                       # older kits' entries, and the native pair once more
            if f not in keep and os.path.exists(os.path.join(apps_dir(), f)):
                os.remove(os.path.join(apps_dir(), f))
        say("menu entries: " + ", ".join(n for _, n, _, _ in shortcut_entries())
            + " - in your applications menu (Games)")
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
        return w[0] if w and w[0] in MODES else "iw4x32"
    except OSError:
        return "iw4x32"


# ---- how to run it: native Linux (Vulkan) or Wine / Proton ------------------------------------------------------------
def read_runtime():
    """files/runtime.txt: the player's last choice (native | wine) - the kit's default when it says nothing"""
    try:
        w = open(F("runtime.txt"), encoding="utf-8", errors="replace").read().split()
        return w[0] if w and w[0] in RUNTIMES else default_runtime()
    except OSError:
        return default_runtime()


def save_runtime(r):
    if r in RUNTIMES:
        try:
            open(F("runtime.txt"), "w").write(r + "\n")
        except OSError:
            pass


def native_path():
    """the loader this kit runs: files/iw4x-native, or - in a private / test kit - the one the environment names"""
    p = os.environ.get("IW4X32_NATIVE")
    p = os.path.expanduser(p) if p else F(NATIVE_FILE)
    return p if os.access(p, os.X_OK) else None


def ldconfig_lines():
    # IW4X32_LDCONFIG: a captured `ldconfig -p` output - the kit tests reproduce a machine that has no i386 runtime
    p = os.environ.get("IW4X32_LDCONFIG")
    if p:
        try:
            return open(p, errors="replace").read()
        except OSError:
            return ""
    # IW4x-32: ldconfig is not on PATH in every environment a start comes from (a menu entry, a test harness):
    # an empty answer here would make "no i386 runtime" and "no 32-bit Vulkan driver" both lies, so the usual
    # Debian/Ubuntu locations are asked by name before the probe gives up on reading the machine.
    for c in (shutil.which("ldconfig"), "/usr/sbin/ldconfig", "/sbin/ldconfig"):
        if not c:
            continue
        try:
            return subprocess.run([c, "-p"], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def native_available():
    """the native run is in THIS kit only when its file set carries the loader - the one switch the promotion is"""
    return os.environ.get("IW4X32_NO_NATIVE") != "1" and native_path() is not None


def default_runtime():
    return "native" if NATIVE_DEFAULT and native_available() and native_ok()[0] else "wine"


def pick_runtime():
    """how THIS start runs: what was asked for, else files/runtime.txt. Asking for the native run in a kit that has
    no loader is an error, not a quiet switch to Wine - the player (or the shortcut) asked for something else."""
    r = O.runtime or read_runtime()
    if r == "native" and not native_available():
        say(f"ERROR: this IW4x-32 has no native loader ({NATIVE_FILE} is not in the kit) - there is no native run "
            "here; start IW4x-32 with --wine, or get a kit that carries it")
        return None
    return r


def i386_libs():
    """the sonames this machine has for a 32-bit process: ldconfig tags them (libc6), the 64-bit ones (libc6,x86-64).
    Empty when ldconfig is missing - then nothing is claimed about the i386 runtime."""
    return {l.strip().split()[0] for l in ldconfig_lines().splitlines() if "(libc6)" in l and "=>" in l}


def missing_i386():
    """the i386 libraries a native start needs: [] when they are all there"""
    have = i386_libs()
    if not have:
        return []                                    # no ldconfig to ask: the loader itself answers
    return sorted({pkg for son, pkg in I386_PKGS.items() if son not in have for pkg in [son]})


def pkg_names(sonames):
    """sonames -> the Debian/Ubuntu packages that carry them, in the order a player can paste them"""
    return " ".join(sorted({I386_PKGS.get(s, s) for s in sonames}))


def icd_manifests():
    """the ICD manifests a Vulkan loader on this machine would read: the system folders, the extra folders
    IW4X32_VK_ICD_DIR names (the kit tests), and VK_DRIVER_FILES / VK_ICD_FILENAMES - the manifest a run is
    pinned to, which is how the test host keeps its driver to the GPU it renders on."""
    dirs = [d for d in ("/usr/share/vulkan/icd.d", "/etc/vulkan/icd.d") if os.path.isdir(d)]
    extra = os.environ.get("IW4X32_VK_ICD_DIR")
    if extra:
        dirs = [d for d in extra.split(os.pathsep) if os.path.isdir(d)] + dirs
    man = [p for d in dirs for p in glob.glob(glob.escape(d) + "/*.json")]
    for var in ("VK_DRIVER_FILES", "VK_ICD_FILENAMES"):
        man += [p for p in os.environ.get(var, "").split(os.pathsep) if p.endswith(".json") and os.path.isfile(p)]
    return man


def icd_is_32(text, have):
    """can a 32-bit process load this driver? A manifest that says so is read as it says (library_arch, or the
    i386 path it loads). Most do not say: the radeon_icd.json mesa-vulkan-drivers installs on a multiarch Ubuntu
    names only "libvulkan_radeon.so", and the LIBRARY decides then - it is loadable in 32-bit exactly when
    ldconfig has that soname for (libc6), which is what mesa-vulkan-drivers:i386 installs. A manifest that names
    no library at all is no Vulkan driver."""
    m = re.search(r'"library_arch"\s*:\s*"(\d+)"', text)
    if m:
        return m.group(1) == "32"
    if re.search(r"/i386-linux-gnu/|/lib32/", text):
        return True
    lib = re.search(r'"library_path"\s*:\s*"([^"]+)"', text)
    return bool(lib) and os.path.basename(lib.group(1)) in have


def vk_device():
    """does this machine have a Vulkan device for a 32-bit process - and if not, which package is missing?
    Two readings, and both have to be right: the 32-bit Vulkan loader, and an installable client driver a 32-bit
    process can load - a 64-bit-only driver on a multiarch machine still leaves a 32-bit process with no device.
    Never starts the game, never opens the GPU: it reads what the machine has installed. IW4X32_VK_ICD_DIR points
    at extra manifest folders (the kit tests reproduce a machine whose drivers are 64-bit only)."""
    have = i386_libs()
    if "libvulkan.so.1" not in have:
        return False, "no 32-bit Vulkan loader (libvulkan.so.1) here - install it: sudo apt install libvulkan1:i386"
    man = icd_manifests()
    n32 = 0
    for p in man:
        try:
            t = open(p, errors="replace").read()
        except OSError:
            continue
        if icd_is_32(t, have):
            n32 += 1
    if not n32:
        who = "no Vulkan driver (ICD) is installed at all" if not man else \
              "the Vulkan drivers here are 64-bit only (no driver a 32-bit process can load), and iw4x-native " \
              "is a 32-bit process"
        return False, (f"{who} - install it: sudo apt install {VK_PKGS['amd']}"
                       f" (AMD/Intel), {VK_PKGS['nvidia']} (NVIDIA)")
    return True, f"{n32} of {len(man)} Vulkan driver(s) loadable by a 32-bit process"


def native_ok():
    """can a native run start on this machine? (ok, why-not) - a missing Vulkan device names the driver package,
    a missing i386 runtime names the exact packages; an unknown answer is a NO, never a quiet maybe"""
    if not native_available():
        return False, (f"this IW4x-32 has no native loader ({NATIVE_FILE} is not in it) - the Wine/Proton run is "
                       "the one this kit ships")
    if os.environ.get("IW4X32_NO_CHECKS") == "1":
        return True, "machine checks skipped (IW4X32_NO_CHECKS=1) - the loader's own error answers instead"
    bad = missing_i386()
    if bad:
        return False, (f"missing 32-bit libraries for iw4x-native: {pkg_names(bad)} "
                       f"- sudo apt install {pkg_names(bad)} {I386_OTHER}")
    return vk_device()


def refuse_native(why):
    """a native start the machine cannot carry: say what is missing, name the package, and leave a non-zero exit.
    Never a silent fall-back to Wine - the player chose the native run."""
    say(f"ERROR: the native Linux run needs something this machine does not have: {why}")
    say("Wine/Proton still works: ./IW4x-32.sh --wine")
    return 1


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


TAIL = ["vanilla", "server", "vanilla-server", "uninstall", "fix"]    # what follows the two Play entries


def select_mode():
    """the start menu. With a native loader in the kit the two ways to run IW4x-32 are side by side - native Linux
    (DXVK-native on Vulkan, no Wine) and Wine/Proton - and N / W switch how Play and Hosting run; the last choice
    is remembered in files/runtime.txt. Without a loader in the kit the menu is the old one."""
    rt = O.runtime or read_runtime()
    if not native_available():
        rt = "wine"
    while True:
        if os.environ.get("IW4X32_NO_MENU") == "1" or not interactive():
            return rt
        nat = native_available()
        play = 0 if rt == "native" else 1
        lines_ = (["  [1] Play IW4x-32, native Linux  the real IW4x client on Vulkan - no Wine, no DX9",
                   "  [2] Play IW4x-32, Wine/Proton   the same client through Steam's Proton or Wine"] if nat else
                  [f"  [1] Play IW4x-32          IW4x-32 servers up to {PLAYERS} players, and normal ones"])
        base = len(lines_)
        lines_ += [f"  [{base + 1}] Play vanilla IW4x     the official IW4x",
                   f"  [{base + 2}] Host a {PLAYERS}-player server   (port {O.port}; "
                   f"{'native Linux' if rt == 'native' else 'Wine/Proton'})",
                   f"  [{base + 3}] Host a normal IW4x server (port {O.port})",
                   f"  [{base + 4}] Uninstall IW4x-32",
                   f"  [{base + 5}] Game crashed / stuck?  closes what is left of it, so Steam can start it again"]
        print(f"\n  IW4x-32 {installed_version()} - Modern Warfare 2 with up to {PLAYERS} players\n  game: {GAME}")
        print(f"  {version_status()}\n")
        for l in lines_:
            print(l)
        if nat:
            ok, why = native_ok()
            print("\n  how it runs: " + ("native Linux (Vulkan)" if rt == "native" else "Wine / Proton")
                  + ("" if ok else f" - not possible on this PC: {why}") + "   (N or W switches it)")
        m = read_mode()
        d = play if m == "iw4x32" else base + TAIL.index(m) if m in TAIL else play
        print(f"  Press 1-{len(lines_)}" + (", N or W" if nat else "") + f" - or wait: [{d + 1}] starts in 5 s ",
              end="", flush=True)
        try:
            c = read_key(5, "\r\n1234567nw")
        except Exception:                                   # no real terminal: a line, then
            c = sys.stdin.readline().strip()[:1].lower() if select.select([sys.stdin], [], [], 5)[0] else ""
        if c in ("n", "w") and nat:
            rt = "native" if c == "n" else "wine"
            save_runtime(rt)                                # switching at the menu is a choice: remember it
            continue
        print(c if c.isdigit() else "")
        i = int(c) - 1 if c.isdigit() and 1 <= int(c) <= len(lines_) else d
        mode = "iw4x32" if i < base else TAIL[i - base]
        O.runtime = rt
        if mode in MODES:
            try:
                open(F("mode.txt"), "w").write(mode + "\n")
            except OSError:
                pass
        save_runtime(rt)
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
    # IW4x-32: the native client's process is the loader itself, not iw4x.exe
    return name.lower().startswith(("iw4x.exe", "iw4x (mm)", "iw4mp.exe", "iw4x-native"))


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
    """the run the player chose: native Linux (Vulkan, no Wine) or Wine / Proton"""
    r = pick_runtime()
    if r is None:
        return 1
    return start_game_native() if r == "native" else start_game_wine()


def start_game_native():
    """the real IW4x client in a native 32-bit process: the loader maps the official iw4x.exe and our iw4x.dll from
    the game folder (IW4X_GAME_DIR) and DXVK-native renders it on Vulkan. No Wine, no Proton, no DX9 driver - and
    the same protocol, so this client joins the same IW4x servers the Wine and Windows players do."""
    b = native_path()
    ok, why = native_ok()
    if not ok:
        return refuse_native(why)
    if not os.path.isfile(G("iw4x.exe")) or not os.path.isfile(G("iw4x.dll")):
        say(f"ERROR: no iw4x.exe / iw4x.dll in {GAME} - run ./IW4x-32.sh --setup")
        return 1
    say(f"starting IW4x-32 natively - 32-bit process, DXVK-native on Vulkan, no Wine ({b})")
    env = dict(os.environ, IW4X_GAME_DIR=GAME, IW4X32_WINDOWED=os.environ.get("IW4X32_WINDOWED", "1"))
    return run([b, GAME] + (["--"] + O.game_args if O.game_args else []), cwd=GAME, env=env)


def start_game_wine():
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


def start_server(slots, cfg, label, runtime=None):
    r = runtime or pick_runtime()
    if r is None:
        return 1
    if r == "native":
        return start_server_native(slots, cfg, label)
    if not os.path.isfile(G("iw4x.exe")):
        say(f"ERROR: no iw4x.exe in {GAME} - run ./IW4x-32.sh --setup")
        return 1
    if slots == PLAYERS and sha(G("iw4x.dll")) != sha(F("iw4x.dll")):
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


def start_server_native(slots, cfg, label):
    """the same dedicated server with no Wine in it: our loader maps the official iw4x.exe + our iw4x.dll. A vanilla
    server (18 slots) is stock IW4x and stays under Wine."""
    if slots != PLAYERS:
        say("a vanilla IW4x server runs the official files - that one runs under Wine")
        return start_server(slots, cfg, label, runtime="wine")
    b = native_path()
    ok, why = native_ok()
    if not ok:
        return refuse_native(why)
    if not os.path.isfile(G("iw4x.exe")) or sha(G("iw4x.dll")) != sha(F("iw4x.dll")):
        say(f"ERROR: IW4x-32 is not installed in {GAME} - run ./IW4x-32.sh --setup")
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
    print(f"  loader:      {b} (no Wine)")
    print(f"  settings:    {os.path.join(user, cfg)}")
    print(f"  port:        {O.port} UDP - forward it on your router for players on the internet")
    print("  bots:        type  spawnBot 10  in the server console")
    env = dict(os.environ, IW4X_GAME_DIR=GAME)
    rc = run([b, GAME, "--"] + sa, cwd=GAME, env=env)
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


# ---- --self-test: this launcher's own logic, on a throwaway tree -----------------------------------------------------
def self_test():
    """python3 files/iw4x32.py --self-test - the launcher's own gates, run here: a fake Steam library, a fake game
    folder, a fake official IW4x launcher and a fake GitHub on localhost, always with IW4X32_NO_START=1, so no game,
    no Wine and no Proton is ever started and nothing outside the throwaway tree is touched. The native loader here
    is a stand-in that only prints its command line: what is under test is the launcher's DECISION, its machine
    checks and the command line it builds. That the real loader really boots the real client is what
    iw4x32/native/tests/kit_native_launch.sh and the test-host runs measure.
    Every gate is also run against the bad case it exists to catch: a gate that can only read "fine" is worthless.
    The machine probes are driven through IW4X32_LDCONFIG / IW4X32_VK_ICD_DIR, so a machine without an i386 runtime
    or without a 32-bit Vulkan driver - what a player without them sees - is reproducible here."""
    global FILES
    import http.server
    import threading
    t = tempfile.mkdtemp(prefix="iw4x32-selftest.")
    CHANGES_MARK = "CHANGES.txt"
    won = [0, 0]

    def gate(ok, what):
        print(("  ok   " if ok else "  FAIL ") + what, flush=True)
        won[0 if ok else 1] += 1

    REV = built_for()                                     # the IW4x release our own dll is built for (its string)
    OFF = f"OFFICIAL-DLL IW4x {REV}"                      # what the fake official IW4x launcher installs
    kit = os.path.join(t, "kit")
    shutil.copytree(KIT, kit, ignore=shutil.ignore_patterns("__pycache__", "backup", "mode.txt", "state.json",
                                                            "runtime.txt"))
    FILES = os.path.join(kit, "files")                    # the probes below read THIS kit, not the one running us
    steam, lib = os.path.join(t, "steam"), os.path.join(t, "lib")
    game = os.path.join(lib, "steamapps", "common", MW2)
    os.makedirs(os.path.join(steam, "steamapps"), exist_ok=True)
    os.makedirs(game, exist_ok=True)
    open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), "w").write(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % lib)
    open(os.path.join(game, "iw4mp.exe"), "w").write("STEAM-MW2")
    proton = os.path.join(lib, "steamapps", "common", "Proton 9.0")
    os.makedirs(os.path.join(lib, "steamapps", "compatdata", "10190", "pfx"), exist_ok=True)
    os.makedirs(os.path.join(proton, "files", "share", "fonts"), exist_ok=True)
    open(os.path.join(proton, "proton"), "w").write("#!/bin/sh\nprintf 'FAKE-PROTON|%s|%s\\n' \"$1\" \"$*\"\n")
    os.chmod(os.path.join(proton, "proton"), 0o755)
    open(os.path.join(lib, "steamapps", "compatdata", "10190", "config_info"), "w").write(
        "Proton 9.0\n%s/files/share/fonts/\n" % proton)
    lch = os.path.join(game, "iw4x-launcher")
    open(lch, "w").write('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PWD/launcher-args.txt"\n'
                         'printf "%s" "$FAKE_IW4X_DLL" > "$PWD/iw4x.dll"\n'
                         '[ -f "$PWD/iw4x.exe" ] || printf OFFICIAL-EXE > "$PWD/iw4x.exe"\n')
    os.chmod(lch, 0o755)

    # the fake GitHub: localhost only, its latest.json signed with a THROWAWAY key (the release key is never here)
    web = os.path.join(t, "web")
    os.makedirs(web, exist_ok=True)
    if not shutil.which("openssl"):
        print("self-test: no openssl to sign the fake releases - the update gates cannot run; no partial pass")
        return 1
    key = os.path.join(t, "test-key.pem")
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", key],
                   check=True, capture_output=True)
    n_hex = subprocess.run(["openssl", "rsa", "-in", key, "-noout", "-modulus"], check=True,
                           capture_output=True, text=True).stdout.strip().split("=", 1)[1].lower()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                          lambda *a: http.server.SimpleHTTPRequestHandler(*a, directory=web))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"

    def publish(d, version):
        root = os.path.join(web, d)
        files = {}
        for dp, _, fns in os.walk(root):
            for fn in fns:
                q = os.path.relpath(os.path.join(dp, fn), root).replace(os.sep, "/")
                files[q] = hashlib.sha256(open(os.path.join(root, q), "rb").read()).hexdigest()
        json.dump({"version": version, "iw4x": REV,
                   "official": {"iw4x.exe": hashlib.sha256(b"OFFICIAL-EXE").hexdigest(),
                                "iw4x.dll": hashlib.sha256(OFF.encode()).hexdigest()},
                   "base_url": f"{url}/{d}/", "files": files, "legacy": []},
                  open(os.path.join(web, "latest.json"), "w"))
        data = open(os.path.join(web, "latest.json"), "rb").read()
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key], input=data, check=True,
                             capture_output=True).stdout
        open(os.path.join(web, "latest.json.sig"), "wb").write(base64.b64encode(sig))

    # a machine that has everything a native run needs, and two that do not - for the probes' bad cases
    ldc_all = os.path.join(t, "ldconfig.i386")
    open(ldc_all, "w").write("".join(f"    {son} (libc6) => /usr/lib/i386-linux-gnu/{son}\n"
                                     for son in list(I386_PKGS)))
    ldc_64 = os.path.join(t, "ldconfig.64only")           # multiarch, but nothing we need in 32-bit
    open(ldc_64, "w").write("".join(f"    {son} (libc6,x86-64) => /lib/x86_64-linux-gnu/{son}\n"
                                    for son in list(I386_PKGS))
                            + "    libgmp.so.10 (libc6) => /usr/lib/i386-linux-gnu/libgmp.so.10\n")
    icd32, icd64, icdnone = (os.path.join(t, x) for x in ("icd32", "icd64", "icdnone"))
    for d, j in ((icd32, '{"library_path": "libradv_i386.so", "library_arch": "32"}'),
                 (icd64, '{"library_path": "libradv.so", "library_arch": "64"}'),
                 (icdnone, '{"library_path": "libGLx.so", "name": "not a Vulkan ICD"}')):
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "x.json"), "w").write(j + "\n")
    # IW4x-32: the shape a real Ubuntu machine has. mesa-vulkan-drivers' radeon_icd.json says nothing about its own
    # architecture - it names "libvulkan_radeon.so" and nothing else - so the LIBRARY is what answers, and
    # mesa-vulkan-drivers:i386 is what puts that soname on the i386 list. The two ldconfig captures below are that
    # machine with and without the :i386 package, and the same manifest is read on both.
    icdplain = os.path.join(t, "icdplain")
    os.makedirs(icdplain, exist_ok=True)
    open(os.path.join(icdplain, "radeon_icd.json"), "w").write(
        '{"ICD": {"api_version": "1.4.335", "library_path": "libvulkan_radeon.so"},\n'
        ' "file_format_version": "1.0.1"}\n')
    ldc_icd32, ldc_icd64 = (os.path.join(t, x) for x in ("ldconfig.icd32", "ldconfig.icd64"))
    shutil.copyfile(ldc_all, ldc_icd32)
    open(ldc_icd32, "a").write("    libvulkan_radeon.so (libc6) => /usr/lib/i386-linux-gnu/libvulkan_radeon.so\n")
    shutil.copyfile(ldc_all, ldc_icd64)
    open(ldc_icd64, "a").write("    libvulkan_radeon.so (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/"
                               "libvulkan_radeon.so\n")
    stub = os.path.join(t, "iw4x-native")                 # the stand-in loader: it only says what it was asked
    open(stub, "w").write('#!/bin/sh\nprintf "STUB-NATIVE|%s|%s\\n" "$PWD" "$*"\n')
    os.chmod(stub, 0o755)
    good_native = dict(IW4X32_NATIVE=stub, IW4X32_LDCONFIG=ldc_all, IW4X32_VK_ICD_DIR=icd32)

    def probe(**over):
        """the machine probes with these settings on top of the ones of a machine that can run native"""
        old = dict(os.environ)
        os.environ.update(good_native)
        for k, v in over.items():
            os.environ.pop(k, None) if v is None else os.environ.update({k: v})
        try:
            return native_ok()
        finally:
            os.environ.clear()
            os.environ.update(old)

    def run_kit(*args, **kw):
        env = dict(os.environ, IW4X32_GAME=game, IW4X32_STEAM=steam, IW4X32_UPDATE_URL=f"{url}/latest.json",
                   IW4X32_LAUNCHER_RELEASE_URL=f"{url}/none", IW4X32_NO_START="1", IW4X32_YES="1",
                   IW4X32_NO_MENU="1", IW4X32_TEST_RELEASE_KEY=f"{n_hex}:10001", FAKE_IW4X_DLL=OFF,
                   XDG_DATA_HOME=os.path.join(t, "xdg"), IW4X32_DESKTOP_DIR=os.path.join(t, "desktop"))
        for k in ("IW4X32_NATIVE", "IW4X32_NO_NATIVE", "IW4X32_NO_CHECKS", "IW4X32_WINDOWED", "IW4X32_VK_ICD_DIR",
                  "IW4X32_LDCONFIG"):
            env.pop(k, None)
        env.update(kw.get("env") or {})
        for k in kw.get("unset") or ():
            env.pop(k, None)
        r = subprocess.run([sys.executable, os.path.join(kit, "files", "iw4x32.py"), *args], env=env,
                           capture_output=True, text=True, input="", timeout=180)
        return r.stdout + r.stderr, r.returncode

    # ---- the machine probes: what a native start is refused for, and the packages it names -----------------------
    ok, why = probe(**good_native)
    gate(ok, f"probes: a machine with the i386 runtime and a 32-bit Vulkan driver says yes ({why})")
    ok, why = probe(IW4X32_LDCONFIG=ldc_64, IW4X32_VK_ICD_DIR=icd32)
    gate(not ok and "libc6:i386" in why and "libsdl2-2.0-0:i386" in why and "sudo apt install" in why,
         "probes: no i386 runtime -> names the exact packages: " + why)
    ok, why = probe(IW4X32_LDCONFIG=ldc_all, IW4X32_VK_ICD_DIR=icd64)
    gate(not ok and "64-bit only" in why and "mesa-vulkan-drivers" in why,
         "probes: Vulkan drivers that are 64-bit only -> says so and names the driver package: " + why)
    ok, why = probe(IW4X32_LDCONFIG=ldc_all, IW4X32_VK_ICD_DIR=icdnone)
    gate(not ok and "64-bit only" in why, "probes: a json that is no Vulkan ICD -> no device: " + why)
    ok, why = probe(IW4X32_LDCONFIG=ldc_all)
    here_ok, here_why = ok, why
    gate(True, f"probes: THIS machine, read for real: {'yes' if ok else 'no'} ({why})")
    # the shape of the machines that really run it: an ICD manifest that says nothing about its own architecture,
    # read on a machine whose driver IS installed for i386 and on one whose driver is 64-bit only
    ok, why = probe(IW4X32_LDCONFIG=ldc_icd32, IW4X32_VK_ICD_DIR=icdplain)
    gate(ok, f"probes: a manifest that names no architecture, driver there for i386 -> yes: {why}")
    ok, why = probe(IW4X32_LDCONFIG=ldc_icd64, IW4X32_VK_ICD_DIR=icdplain)
    gate(not ok and "64-bit only" in why and "mesa-vulkan-drivers" in why,
         "probes: that same manifest, driver 64-bit only -> names the driver package: " + why)
    # the test host pins its driver with VK_DRIVER_FILES: the manifest IT points at is the reading that counts
    ok, why = probe(IW4X32_LDCONFIG=ldc_icd64, IW4X32_VK_ICD_DIR=None, VK_DRIVER_FILES=os.path.join(icd32, "x.json"))
    gate(ok, f"probes: VK_DRIVER_FILES pins a 32-bit driver the system folders do not carry -> yes: {why}")
    ok, why = probe(IW4X32_LDCONFIG=ldc_icd64, IW4X32_VK_ICD_DIR=None,
                    VK_ICD_FILENAMES=os.path.join(icd64, "x.json"))
    gate(not ok and "64-bit only" in why, "probes: VK_ICD_FILENAMES pinning a 64-bit driver -> no device: " + why)
    old_files = FILES
    FILES = os.path.join(os.path.join(t, "kit"), "files")     # this kit's file set: no iw4x-native in it
    ok, why = probe(IW4X32_NATIVE=None)
    gate(not ok and NATIVE_FILE in why, "probes: a kit without files/iw4x-native has no native run: " + why)
    FILES = old_files

    # ---- the public kit (no loader in its file set): native is refused, Wine/Proton is not demoted ----------------
    out, rc = run_kit("--native", "--dry")
    gate(rc != 0 and "no native loader" in out and "command:" not in out,
         "public kit: --native is refused with a reason and a non-zero exit (no silent switch to Wine)")
    out, rc = run_kit("--wine", "--dry")
    gate(rc == 0 and "command:" in out and "iw4x-native" not in out and "proton" in out,
         "public kit: --wine still starts the game through the game's Proton")
    out, rc = run_kit("--dry")
    gate(rc == 0 and "proton" in out and "iw4x-native" not in out,
         "public kit: with no runtime.txt the run is Wine/Proton (NATIVE_DEFAULT is off)")

    # ---- a kit that carries the loader (a private / test kit) -----------------------------------------------------
    put = os.path.join(kit, "files", NATIVE_FILE)
    shutil.copy2(stub, put)
    os.chmod(put, 0o755)
    base = dict(good_native)
    out, rc = run_kit("--native", "--dry", env=base)
    cmd = [l for l in out.splitlines() if l.strip().startswith("command:")]
    gate(rc == 0 and cmd and "iw4x-native" in cmd[0] and game in cmd[0] and "wine" not in cmd[0]
         and "proton" not in cmd[0], "native kit: --native starts the loader, no Wine / Proton in the command")
    out, rc = run_kit("--native", env=base, unset=("IW4X32_NO_START",))   # the loader really runs and says what it got
    got = [l for l in out.splitlines() if l.startswith("STUB-NATIVE|")]
    gate(got and got[0].split("|")[1] == game and got[0].count("|") >= 2,
         "native kit: the loader was started in the game folder with the game's own arguments")
    out, rc = run_kit("--native-server", "28961", env=base)
    gate(rc == 0 and f"sv_maxclients {PLAYERS}" in out and "net_port 28961" in out and "no Wine" in out
         and "wine iw4x.exe" not in out, f"native kit: hosting a {PLAYERS}-player server natively, on the asked port")
    out, rc = run_kit("--wine", "--server", "28962", env=base)
    cmds = [l for l in out.splitlines() if "command:" in l]
    gate(rc == 0 and cmds and "wine iw4x.exe" in cmds[0] and "iw4x-native" not in cmds[0]
         and "net_port 28962" in out,
         "native kit: hosting with --wine is the Proton/Wine server - both ways stay first-class")
    out, rc = run_kit("--vanilla-server", env=base)
    gate(rc == 0 and "sv_maxclients 18" in out, "native kit: a vanilla (official) server still runs the official files")
    out, rc = run_kit("--native", "--dry", env=dict(base, IW4X32_VK_ICD_DIR=icd64))
    gate(rc != 0 and "mesa-vulkan-drivers" in out and "command:" not in out,
         "native kit: no Vulkan device for a 32-bit process -> names the driver package and exits non-zero")
    out, rc = run_kit("--native", "--dry", env=dict(base, IW4X32_LDCONFIG=ldc_64))
    gate(rc != 0 and "libc6:i386" in out and "command:" not in out,
         "native kit: missing i386 runtime -> names the exact packages and exits non-zero")
    gate(os.path.isfile(os.path.join(kit, "files", "runtime.txt"))
         and open(os.path.join(kit, "files", "runtime.txt")).read().strip() == "native",
         "native kit: the player's last choice is remembered in files/runtime.txt")
    out, rc = run_kit("--dry", env=base)
    gate("iw4x-native" in out and "proton" not in out, "native kit: the remembered choice is what the bare start runs")
    out, rc = run_kit("--wine", "--dry", env=base)
    gate("proton" in out and open(os.path.join(kit, "files", "runtime.txt")).read().strip() == "wine",
         "native kit: --wine switches it back and that is what is remembered")

    # ---- the app-menu entries, one per way to run -----------------------------------------------------------------
    ddir = os.path.join(t, "desktop")
    g2 = os.path.join(lib, "steamapps", "common", MW2 + "-two")
    os.makedirs(g2, exist_ok=True)
    open(os.path.join(g2, "iw4mp.exe"), "w").write("STEAM-MW2")
    shutil.copy2(lch, os.path.join(g2, "iw4x-launcher"))
    out, rc = run_kit("--setup", g2, env=base)
    names = sorted(os.listdir(ddir)) if os.path.isdir(ddir) else []
    gate("iw4x32.desktop" in names and "iw4x32-wine.desktop" in names and "iw4x32-native.desktop" in names
         and "iw4x32-native-server.desktop" in names, "menu entries: one per option, native included: " + " ".join(names))
    nat = open(os.path.join(ddir, "iw4x32-native.desktop"), errors="replace").read()
    gate("--native" in nat and "--wine" not in nat, "menu entry: the native one really starts the native run")
    os.remove(put)                                             # this kit no longer carries the loader (the public one)
    g3 = os.path.join(lib, "steamapps", "common", MW2 + "-three")
    os.makedirs(g3, exist_ok=True)
    open(os.path.join(g3, "iw4mp.exe"), "w").write("STEAM-MW2")
    shutil.copy2(lch, os.path.join(g3, "iw4x-launcher"))
    run_kit("--setup", g3)
    names = sorted(os.listdir(ddir))
    gate("iw4x32-native.desktop" not in names and "iw4x32-wine.desktop" in names,
         "public kit: no native menu entries, and the old ones are removed again")

    # ---- self-update: the native loader keeps its exec bit, and a signed release still swaps in --------------------
    shutil.copy2(stub, put)                                    # the kit carries the loader again for the release
    os.chmod(put, 0o755)
    # the version test needs a real difference between the installed kit and the game's copy of it
    open(os.path.join(kit, "files", CHANGES_MARK), "w", newline="").write("self-test\r\n")
    os.chmod(os.path.join(kit, "files", NATIVE_FILE), 0o644)   # an install that lost the loader's exec bit
    shutil.rmtree(os.path.join(web, "rel99"), ignore_errors=True)
    shutil.copytree(kit, os.path.join(web, "rel99"), ignore=shutil.ignore_patterns("backup"))
    readme = open(os.path.join(web, "rel99", "README.txt"), encoding="utf-8", errors="replace").read()
    open(os.path.join(web, "rel99", "README.txt"), "w", newline="").write(
        readme.replace(installed_version(kit), "v9.99-" + REV, 1))
    open(os.path.join(web, "rel99", "files", CHANGES_MARK), "w", newline="").write("changed\r\n")
    # the release's loader differs by one comment, so the update really re-downloads it: that is the only way the
    # exec bit is measured and not read as "fine" by luck (an unchanged file is never downloaded at all)
    open(os.path.join(web, "rel99", "files", NATIVE_FILE), "a").write("# v9.99\n")
    publish("rel99", "v9.99-" + REV)
    out, rc = run_kit("--play", env=base)                             # NO_START=1: it prints the start, runs nothing
    gate("v9.99-" + REV in out and installed_version(kit) == "v9.99-" + REV,
         "update: a signed release whose file set carries the loader updates the kit")
    gate(os.access(os.path.join(kit, "files", NATIVE_FILE), os.X_OK),
         "update: files/iw4x-native comes back executable (a native kit is useless without its exec bit)")
    gate(os.access(os.path.join(kit, "files", "iw4x32.py"), os.X_OK) and os.access(os.path.join(kit, "IW4x-32.sh"), os.X_OK),
         "update: the scripts keep their exec bits too")
    os.remove(os.path.join(web, "latest.json.sig"))
    out, rc = run_kit("--play", env=base)
    gate("update refused" in out and "command:" in out, "update: an unsigned release is refused and the game starts anyway")

    print(f"\nself-test: {won[0]} passed, {won[1]} failed  (tree: {t})")
    return 0 if won[1] == 0 else 1


def main():
    global GAME
    parse(sys.argv[1:])
    if not os.path.isfile(F("iw4x.dll")):
        # only IW4x-32.sh was downloaded (or the zip was not fully extracted): get the rest of the release
        say("getting IW4x-32 from GitHub ...")
        update_kit(get_manifest(timeout=30))
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
    if O.runtime:
        save_runtime(O.runtime)                          # a shortcut / --native is the player's choice too
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
        nat = pick_runtime() == "native"
        return start_server(PLAYERS, "server_iw4x32.cfg",
                            f"IW4x-32 server - {PLAYERS} players" + (", native Linux (no Wine)" if nat else ""))
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
