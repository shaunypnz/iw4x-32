#!/usr/bin/env bash
# upd_test.sh - run the kit's updater (iw4x32_update.py) against a fake game folder and a local "GitHub": no
# network, no real game, nothing of ours installed anywhere. Proves the v2.0 rules hold:
#   - only files/iw4x.dll goes into the game folder; an iw4x.exe left by a v1.x install is restored from backup/
#   - the official dll is backed up before ours goes in
#   - a newer manifest updates the kit (README v2.0 -> v2.1); a second run changes nothing
#   - if the IW4x launcher put the official dll back, the next start puts ours back
#   - a download whose bytes do not match latest.json's SHA-256 installs nothing at all
# Usage: bash iw4x32/tools/upd_test.sh          (test tree left under .scratch/, printed at the end)
set -euo pipefail
KIT_SRC=${KIT_SRC:-iw4x32/release}
T=$(mktemp -d "$PWD/.scratch/upd-test.XXXX")
GAME=$T/game; KIT=$T/kit; WEB=$T/web
mkdir -p "$GAME" "$WEB" "$KIT/backup"
cp -a "$KIT_SRC"/. "$KIT"
rm -f "$KIT/mode.txt"

# fake official r5154 files in the game folder, a v1.x iw4x.exe left there, the v1.x backup, a fake IW4x launcher
printf 'OFFICIAL-DLL-CONTENT' > "$GAME/iw4x.dll"
printf 'V1-EXE-CONTENT' > "$GAME/iw4x.exe"
printf 'official-exe-backup' > "$KIT/backup/iw4x.exe"
printf '#!/bin/sh\nexit 0\n' > "$GAME/iw4x-launcher"; chmod +x "$GAME/iw4x-launcher"

# point the updater's v1.x-exe constant at our fake file
V1=$(sha256sum "$GAME/iw4x.exe" | cut -d' ' -f1)
sed -i "s/^V1_EXE = \"[0-9a-f]*\"/V1_EXE = \"$V1\"/" "$KIT/iw4x32_update.py"
grep -q "V1_EXE = \"$V1\"" "$KIT/iw4x32_update.py"

# manifest writer: hashes what is in $WEB/iw4x32/release; --wrong FILE simulates a download that is not what
# latest.json describes (corrupt file, truncated transfer, hostile server)
export OFFICIAL_DLL=OFFICIAL-DLL-CONTENT OFFICIAL_EXE=official-exe-backup
manifest() {
    python3 - "$WEB" "$GAME" "$KIT" "$@" <<'EOF'
import hashlib, json, os, sys
web, game, kit = (os.path.abspath(p) for p in sys.argv[1:4])
args, OFFICIAL = sys.argv[4:], (os.environ["OFFICIAL_DLL"], os.environ["OFFICIAL_EXE"])
version, wrong = args[args.index("--version") + 1], None
if "--wrong" in args:
    wrong = args[args.index("--wrong") + 1]
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
root = os.path.join(web, "iw4x32", "release")
files = {}
for d, sub, names in os.walk(root):
    for n in names:
        p = os.path.relpath(os.path.join(d, n), root).replace(os.sep, "/")
        if p != "SHA256SUMS.txt":
            files[p] = sha(os.path.join(root, p))
if wrong:
    files[wrong] = "0" * 64
m = {"version": version, "iw4x": "r5154",
     "official": {"iw4x.dll": hashlib.sha256(OFFICIAL[0].encode()).hexdigest(),
                  "iw4x.exe": hashlib.sha256(OFFICIAL[1].encode()).hexdigest()},
     "base_url": "file://" + root + "/", "files": files}
json.dump(m, open(os.path.join(web, "latest.json"), "w"), indent=1)
EOF
}
mkdir -p "$WEB/iw4x32/release"
cp -a "$KIT"/. "$WEB/iw4x32/release/"
sed -i '1s/IW4x-32 v[0-9.]*/IW4x-32 v2.1/' "$WEB/iw4x32/release/README.txt"   # the new release
manifest --version v2.1
printf '{"tag_name": "r5154"}\n' > "$WEB/iw4x-latest.json"
sed -i '1s/IW4x-32 v[0-9.]*/IW4x-32 v2.0/' "$KIT/README.txt"                  # what is installed here

# the installers refuse to touch a running game (pgrep -x iw4x.exe) - a test run must not depend on what the
# machine happens to have started, so a pgrep that reports "nothing running" goes first on PATH
mkdir -p "$T/bin"; printf '#!/bin/sh\nexit 1\n' > "$T/bin/pgrep"; chmod +x "$T/bin/pgrep"
export PATH="$T/bin:$PATH"

run_upd() {   # the updater's exit code is information (0 current, 10 kit updated, 1 error): set -e must not eat it
    env IW4X32_GAME="$GAME" IW4X32_NO_MENU=1 IW4X32_NO_START=1 \
        IW4X32_UPDATE_URL="file://$WEB/latest.json" IW4X32_IW4X_LATEST_URL="file://$WEB/iw4x-latest.json" \
        python3 "$KIT/iw4x32_update.py" --iw4x32 || echo "  updater exit=$?"
}
same() { cmp -s "$1" "$2" && echo "  OK   $3" || echo "  FAIL $3"; }
ver() { head -1 "$KIT/README.txt" | grep -oE 'v[0-9]+(\.[0-9]+)*' | head -1; }

echo "== run 1: v2.1 available, IW4x already the version it is made for =="
run_upd
same "$GAME/iw4x.dll" "$KIT/files/iw4x.dll" "game iw4x.dll is ours (files/iw4x.dll)"
same "$GAME/iw4x.exe" "$KIT/backup/iw4x.exe" "game iw4x.exe is the one from backup/ (v1.x cleanup)"
same <(printf 'OFFICIAL-DLL-CONTENT') "$KIT/backup/iw4x.dll" "backup holds the official dll"
[ "$(ver)" = v2.1 ] && echo "  OK   kit updated to v2.1" || echo "  FAIL kit is at $(ver)"
echo "  game folder: $(ls "$GAME" | tr '\n' ' ')"

echo "== run 2: everything current =="
run_upd
same "$GAME/iw4x.dll" "$KIT/files/iw4x.dll" "still ours, nothing changed"

echo "== run 3: the IW4x launcher put the official dll back -> repair =="
printf 'OFFICIAL-DLL-CONTENT' > "$GAME/iw4x.dll"
run_upd
same "$GAME/iw4x.dll" "$KIT/files/iw4x.dll" "ours is installed again"

echo "== run 4: a download that is not what latest.json says must change nothing =="
sed -i '1s/IW4x-32 v[0-9.]*/IW4x-32 v2.2/' "$WEB/iw4x32/release/README.txt"
manifest --version v2.2 --wrong README.txt
run_upd
same "$GAME/iw4x.dll" "$KIT/files/iw4x.dll" "game folder untouched"
[ "$(ver)" = v2.1 ] && echo "  OK   kit still at v2.1 (nothing swapped in)" || echo "  FAIL kit is at $(ver)"

echo "test tree: $T"
