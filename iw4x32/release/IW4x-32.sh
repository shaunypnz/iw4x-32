#!/bin/sh
# IW4x-32 - Modern Warfare 2 with up to 48 players (Linux / Steam Deck, Steam Proton or Wine). Run:  ./IW4x-32.sh
#  First time: finds your game, installs official IW4x (with the official IW4x launcher) and IW4x-32, and adds
#  "IW4x-32" to your applications menu. After that it is the start menu: play, vanilla IW4x, host a server,
#  uninstall. It keeps itself and IW4x up to date.
# This file is enough on its own: without the files/ folder next to it, it downloads the release from GitHub
# (every file SHA-256 checked) into an IW4x-32 folder next to it first.
# Options: ./IW4x-32.sh --help. Everything happens in files/iw4x32.py.
D=$(cd "$(dirname "$0")" && pwd)
P="$D/files/iw4x32.py"
[ -f "$P" ] || P="$D/IW4x-32/files/iw4x32.py"
command -v python3 >/dev/null 2>&1 || { echo "IW4x-32 needs python3 (Debian/Ubuntu: sudo apt install python3)"; exit 1; }
if [ ! -f "$P" ]; then
    echo "Downloading IW4x-32 ..."
    python3 - "$P" <<'EOF' || { echo "Could not download IW4x-32 - get the zip from https://github.com/shaunypnz/iw4x-32/releases"; exit 1; }
import hashlib, json, os, sys, urllib.request
get = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "iw4x32-setup"}), timeout=60).read()
m = json.loads(get(os.environ.get("IW4X32_UPDATE_URL") or "https://github.com/shaunypnz/iw4x-32/releases/latest/download/latest.json"))
b = get(m["base_url"] + "files/iw4x32.py")
if hashlib.sha256(b).hexdigest() != m["files"]["files/iw4x32.py"]:
    sys.exit("download check failed")
os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)
open(sys.argv[1], "wb").write(b)
EOF
fi
exec python3 "$P" "$@"
