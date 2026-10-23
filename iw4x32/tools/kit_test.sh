#!/usr/bin/env bash
# kit_test.sh - run the kit's launchers (files/iw4x32.py, and files/iw4x32.ps1 under pwsh) against a fake Steam
# library, a fake game folder, a fake official IW4x launcher and a local "GitHub" - no network, no real game,
# nothing installed anywhere outside the test tree. Both launchers go through the same cases:
#   setup from an extracted zip: finds MW2 in Steam, copies the kit to <game>/IW4x-32, the official launcher installs
#   IW4x, the official dll is backed up, ours goes in; a second start changes nothing; the IW4x launcher putting the
#   official dll back is repaired; server (port, 32 slots, userraw cfg); vanilla puts the official dll back; a new
#   release updates the kit (legacy shims skipped), a second run downloads nothing; a download with a wrong SHA-256
#   changes nothing and the game still starts; an older copy of the kit hands over to the newer one in the game
#   folder; versions (built-for x from our dll, your IW4x y from the official one): a newer y stays, an older y is
#   updated by the official launcher (at most every 15 min); the official launcher gets the official dll and
#   --skip-remote when it checked online recently; a v2.0 folder is migrated through its old entry point
#   (iw4x32_update.py / .ps1); uninstall; --fix closes a crashed game's leftovers (py); only the launcher script
#   downloaded (bootstrap).
# Usage: bash iw4x32/tools/kit_test.sh [py|ps1]...      (default: both; test tree left under .scratch/)
set -uo pipefail
KIT_SRC=${KIT_SRC:-iw4x32/release}
IMPLS=("$@"); [ ${#IMPLS[@]} = 0 ] && IMPLS=(py ps1)
mkdir -p .scratch
T=$(mktemp -d "$PWD/.scratch/kit-test.XXXX")
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); echo "  ok   $*"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL $*"; }
has() { grep -qF -- "$2" "$1" && ok "$3" || { bad "$3 (no '$2' in output)"; sed 's/^/       | /' "$1" | tail -15; }; }
hasnt() { grep -qF -- "$2" "$1" && { bad "$3 ('$2' in output)"; sed 's/^/       | /' "$1" | tail -15; } || ok "$3"; }
same() { [ "$(cat "$1" 2>/dev/null | sha256sum)" = "$(cat "$2" 2>/dev/null | sha256sum)" ] && ok "$3" || bad "$3"; }
sha() { printf %s "$1" | sha256sum | cut -d' ' -f1; }
# x = the IW4x release our dll is built for (its strings say "IW4x rNNNN"); the fake official dll says the same
X=$(grep -aoE 'IW4x \(?r[0-9]{4,}' "$KIT_SRC/files/iw4x.dll" | head -1 | grep -oE 'r[0-9]+')
[ -n "$X" ] || { echo "no IW4x version in $KIT_SRC/files/iw4x.dll"; exit 1; }
OFF="OFFICIAL-DLL IW4x $X"; export FAKE_OFF=$OFF

# ---- the local "GitHub" -------------------------------------------------------------------------------------------
WEB=$T/web; mkdir -p "$WEB/iw4x"
python3 -u -m http.server 0 --bind 127.0.0.1 --directory "$WEB" > "$T/http.log" 2>&1 &
HTTP=$!; trap 'kill $HTTP 2>/dev/null' EXIT
for _ in $(seq 50); do PORT=$(grep -o 'port [0-9]*' "$T/http.log" | cut -d' ' -f2); [ -n "$PORT" ] && break; sleep 0.1; done
URL=http://127.0.0.1:$PORT
manifest() {   # manifest <dir under web> <version> [file-with-wrong-hash]: writes $WEB/latest.json
    python3 - "$WEB" "$1" "$2" "${3:-}" "$URL" <<'EOF'
import hashlib, json, os, sys
web, d, ver, wrong, url = sys.argv[1:]
root = os.path.join(web, d)
files = {}
for dp, dn, fn in os.walk(root):
    for n in fn:
        p = os.path.relpath(os.path.join(dp, n), root).replace(os.sep, "/")
        files[p] = hashlib.sha256(open(os.path.join(dp, n), "rb").read()).hexdigest()
if wrong:
    files[wrong] = "0" * 64
off = {"iw4x.dll": hashlib.sha256(os.environ["FAKE_OFF"].encode()).hexdigest(), "iw4x.exe": hashlib.sha256(b"OFFICIAL-EXE").hexdigest()}
json.dump({"version": ver, "iw4x": os.environ["FAKE_OFF"].split()[-1], "official": off, "base_url": f"{url}/{d}/", "files": files,
           "legacy": ["iw4x32_update.ps1", "iw4x32_update.py"]}, open(os.path.join(web, "latest.json"), "w"))
EOF
}

# ---- the kit as a player extracts it, its constants pointed at our fake official / v1.x files -----------------------
KIT0=$T/kit0
cp -a "$KIT_SRC" "$KIT0"
find "$KIT0" -name __pycache__ -prune -exec rm -rf {} +
for f in "$KIT0/files/iw4x32.py" "$KIT0/files/iw4x32.ps1"; do
    sed -i -E "s/^(\\\$?OFFICIAL_DLL = .)[0-9a-f]+/\\1$(sha "$OFF")/; s/^(\\\$?OFFICIAL_EXE = .)[0-9a-f]+/\\1$(sha OFFICIAL-EXE)/; s/^(\\\$?V1_EXE = .)[0-9a-f]+/\\1$(sha V1-EXE)/" "$f"
    grep -q "$(sha "$OFF")" "$f" || { echo "could not point $f at the fake files"; exit 1; }
done
# release v2.0 = this kit; release v9.9 = this kit with a new README line 1 and a changed CHANGES.txt
cp -a "$KIT0" "$WEB/rel20"
cp -a "$KIT0" "$WEB/rel99"
sed -i '1s/v[0-9.]*/v9.9/' "$WEB/rel99/README.txt"; printf 'new\r\n' >> "$WEB/rel99/files/CHANGES.txt"

fake_game() {   # fake_game <dir>: an MW2 folder from Steam (no IW4x yet) with the official IW4x launcher in it
    mkdir -p "$1"; printf 'STEAM-MW2' > "$1/iw4mp.exe"
    cat > "$1/iw4x-launcher" <<'EOF'
#!/bin/sh
printf '%s | dll: %s\n' "$*" "$(head -c 40 "$PWD/iw4x.dll" 2>/dev/null | tr -d '\0')" >> "$PWD/launcher-args.txt"
printf '%s' "${FAKE_IW4X_DLL:-$FAKE_OFF}" > "$PWD/iw4x.dll"
[ -f "$PWD/iw4x.exe" ] && [ "$(cat "$PWD/iw4x.exe")" = V1-EXE ] || printf 'OFFICIAL-EXE' > "$PWD/iw4x.exe"
EOF
    chmod +x "$1/iw4x-launcher"
}

for IMPL in "${IMPLS[@]}"; do
    echo "== $IMPL"
    PWSH=$(command -v pwsh || ls "$HOME/.local/bin/pwsh" /opt/microsoft/powershell/7/pwsh 2>/dev/null | head -1)
    if [ "$IMPL" = ps1 ] && [ -z "$PWSH" ]; then bad "pwsh is not installed - the .ps1 was not tested"; continue; fi
    R=$T/$IMPL; mkdir -p "$R"
    STEAM=$R/steam; LIB=$R/lib; GAME="$LIB/steamapps/common/Call of Duty Modern Warfare 2"
    mkdir -p "$STEAM/steamapps"
    printf '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t\t"apps"\n\t\t{\n\t\t\t"10190"\t\t"123"\n\t\t}\n\t}\n}\n' "$LIB" \
        > "$STEAM/steamapps/libraryfolders.vdf"
    fake_game "$GAME"
    # the game's Proton prefix and the Proton that made it (what Steam leaves after MW2 ran once)
    mkdir -p "$LIB/steamapps/compatdata/10190/pfx" "$LIB/steamapps/common/Proton 9.0/files/share/fonts"
    printf '#!/bin/sh\n' > "$LIB/steamapps/common/Proton 9.0/proton"; chmod +x "$LIB/steamapps/common/Proton 9.0/proton"
    printf 'Proton 9.0\n%s\n' "$LIB/steamapps/common/Proton 9.0/files/share/fonts/" > "$LIB/steamapps/compatdata/10190/config_info"
    cp -a "$KIT0" "$R/download"; rm -f "$R/download/iw4x32_update.ps1" "$R/download/iw4x32_update.py"
    export IW4X32_STEAM=$STEAM IW4X32_UPDATE_URL=$URL/latest.json \
        IW4X32_LAUNCHER_RELEASE_URL=$URL/none IW4X32_NO_START=1 XDG_DATA_HOME=$R/xdg
    unset IW4X32_YES FAKE_IW4X_DLL
    run() {   # run <kit dir> <output file> args...
        local k=$1 o=$2; shift 2
        if [ "$IMPL" = py ]; then python3 "$k/files/iw4x32.py" "$@" </dev/null >"$o" 2>&1
        else "$PWSH" -NoProfile -NonInteractive -File "$k/files/iw4x32.ps1" "$@" </dev/null >"$o" 2>&1; fi
    }
    manifest rel20 v2.0

    # 1. setup from the extracted zip
    run "$R/download" "$R/1.out"
    K="$GAME/IW4x-32"
    [ -f "$K/files/iw4x32.$IMPL" ] && ok "setup copied the kit into the game folder" || bad "setup did not copy the kit"
    same "$GAME/iw4x.dll" "$KIT0/files/iw4x.dll" "IW4x-32's iw4x.dll is installed"
    [ "$(cat "$K/files/backup/iw4x.dll" 2>/dev/null)" = "$OFF" ] && ok "the official dll is backed up in files/backup" || bad "no backup of the official dll"
    grep -q -- --skip-launch "$GAME/launcher-args.txt" 2>/dev/null && ok "the official launcher installed IW4x (--skip-launch)" || bad "the official launcher was not run"
    has "$R/1.out" "command:" "setup goes on to start the game"
    has "$R/1.out" "built for IW4x $X, your IW4x is $X - they match" "setup: built-for and installed IW4x versions shown"
    if [ "$IMPL" = py ]; then [ -f "$R/xdg/applications/iw4x32.desktop" ] && ok "menu entry made" || bad "no menu entry"; fi

    # 2. a second start changes nothing
    rm -f "$GAME/launcher-args.txt"
    run "$K" "$R/2.out" --play
    [ ! -f "$GAME/launcher-args.txt" ] && ok "second start: the official launcher is not run" || bad "second start ran the launcher"
    hasnt "$R/2.out" "downloading" "second start downloads nothing"
    has "$R/2.out" "command:" "second start starts the game"

    # 3. the IW4x launcher's file check put the official dll back
    printf '%s' "$OFF" > "$GAME/iw4x.dll"
    run "$K" "$R/3.out" --play
    same "$GAME/iw4x.dll" "$KIT0/files/iw4x.dll" "repair: IW4x-32 is put back"

    # 4. a 32-player server on another port
    run "$K" "$R/4.out" --server 28961
    [ -f "$GAME/userraw/server_iw4x32.cfg" ] && ok "server: userraw/server_iw4x32.cfg made" || bad "server: no userraw cfg"
    has "$R/4.out" "net_port 28961" "server: the port is passed on"
    has "$R/4.out" "sv_maxclients 32" "server: 32 slots"

    # 5. vanilla puts the official dll back, IW4x-32 puts itself back
    run "$K" "$R/5.out" --vanilla
    [ "$(cat "$GAME/iw4x.dll")" = "$OFF" ] && ok "vanilla: the official dll is back" || bad "vanilla: official dll not restored"
    run "$K" "$R/5b.out" --play
    same "$GAME/iw4x.dll" "$KIT0/files/iw4x.dll" "after vanilla, IW4x-32 puts itself back"
    # vanilla for real (the fake launcher): it gets the official dll, and no online check right after setup's
    rm -f "$GAME/launcher-args.txt"
    IW4X32_NO_START= run "$K" "$R/5c.out" --vanilla
    grep -qF "dll: $OFF" "$GAME/launcher-args.txt" 2>/dev/null && ok "vanilla: the official launcher sees the official dll" || bad "vanilla: launcher got IW4x-32's dll"
    grep -q -- "--skip-remote" "$GAME/launcher-args.txt" 2>/dev/null && ok "vanilla: --skip-remote within 15 min of the last online check" || bad "vanilla: online check again"
    rm -f "$K/files/state.json" "$GAME/launcher-args.txt"
    IW4X32_NO_START= run "$K" "$R/5d.out" --vanilla
    grep -q -- "--skip-remote" "$GAME/launcher-args.txt" 2>/dev/null && bad "vanilla: --skip-remote with no recent check" || ok "vanilla: online check when none was recent"
    run "$K" "$R/5e.out" --play

    # 6. a new release
    manifest rel99 v9.9
    run "$K" "$R/6.out" --play
    head -1 "$K/README.txt" | grep -q v9.9 && ok "update: the kit is now v9.9" || bad "update: README is not v9.9"
    same "$K/files/CHANGES.txt" "$WEB/rel99/files/CHANGES.txt" "update: changed file downloaded"
    [ ! -e "$K/iw4x32_update.py" ] && [ ! -e "$K/iw4x32_update.ps1" ] && ok "update: the v2.0 shims are not downloaded" || bad "update downloaded the legacy shims"
    has "$R/6.out" "command:" "update: the game starts"
    run "$K" "$R/6b.out" --play
    hasnt "$R/6b.out" "downloading" "after the update nothing is downloaded again"

    # 7. a download that does not match latest.json changes nothing
    cp -a "$WEB/rel99" "$WEB/rel910"; sed -i '1s/v9.9/v9.10/' "$WEB/rel910/README.txt"
    manifest rel910 v9.10 files/CHANGES.txt
    run "$K" "$R/7.out" --play
    has "$R/7.out" "download check failed" "bad hash: refused"
    head -1 "$K/README.txt" | grep -q 'v9.9 ' && ok "bad hash: nothing was changed" || bad "bad hash: the kit changed"
    has "$R/7.out" "command:" "bad hash: the game still starts"
    manifest rel99 v9.9

    # 7b. an older copy of the kit (the extracted v2.0 zip) hands over to the v9.9 in the game folder
    rm -f "$GAME/launcher-args.txt"
    run "$R/download" "$R/7b.out" --play
    has "$R/7b.out" "already set up" "older copy: hands over to the installed IW4x-32"
    hasnt "$R/7b.out" "copying IW4x-32" "older copy: not copied over the newer one"
    head -1 "$K/README.txt" | grep -q 'v9.9 ' && ok "older copy: the game folder keeps v9.9" || bad "older copy: downgraded the kit"
    [ ! -f "$GAME/launcher-args.txt" ] && ok "older copy: the official launcher is not run" || bad "older copy ran the official launcher"
    has "$R/7b.out" "command:" "older copy: the game starts"

    # 8. versions: the official launcher (vanilla) installed a NEWER IW4x: it stays, IW4x-32 runs its own build
    printf 'OFFICIAL-DLL IW4x r9999' > "$GAME/iw4x.dll"; rm -f "$GAME/launcher-args.txt"
    run "$K" "$R/8.out" --play
    has "$R/8.out" "your IW4x is r9999 (newer) - vanilla IW4x runs r9999, IW4x-32 runs its own $X build" "newer IW4x: both versions said"
    [ "$(cat "$K/files/backup/iw4x.dll")" = "OFFICIAL-DLL IW4x r9999" ] && ok "newer IW4x: it is the backup (vanilla runs it)" || bad "newer IW4x: not backed up"
    same "$GAME/iw4x.dll" "$KIT0/files/iw4x.dll" "newer IW4x: IW4x-32 is in"
    [ ! -f "$GAME/launcher-args.txt" ] && ok "newer IW4x: the official launcher is not run" || bad "newer IW4x: launcher run"
    has "$R/8.out" "command:" "newer IW4x: the game starts"
    # an OLDER IW4x: the official launcher updates it (it brings $X), once per 15 min
    printf 'OFFICIAL-DLL IW4x r1000' > "$GAME/iw4x.dll"; rm -f "$K/files/state.json"
    run "$K" "$R/8b.out" --play
    grep -q -- --skip-launch "$GAME/launcher-args.txt" 2>/dev/null && ok "older IW4x: the official launcher updates it" || bad "older IW4x: not updated"
    [ "$(cat "$K/files/backup/iw4x.dll")" = "$OFF" ] && ok "older IW4x: the updated one is the backup" || bad "older IW4x: backup not updated"
    has "$R/8b.out" "they match" "older IW4x: versions match after the update"
    printf 'OFFICIAL-DLL IW4x r1000' > "$GAME/iw4x.dll"; rm -f "$GAME/launcher-args.txt"
    run "$K" "$R/8c.out" --play
    [ ! -f "$GAME/launcher-args.txt" ] && ok "older IW4x again: no second launcher run within 15 min" || bad "older IW4x: launcher run twice in 15 min"
    has "$R/8c.out" "command:" "older IW4x again: the game starts"
    printf '%s' "$OFF" > "$GAME/iw4x.dll"; run "$K" "$R/8d.out" --play

    # 9. a v2.0 folder started through its old entry point
    mv "$K/files/backup" "$K/backup"; printf 'old' > "$K/Play IW4x-32.bat"; mkdir -p "$K/server"; printf 'x' > "$K/server/server_iw4x32.cfg"
    mkdir -p "$K/source"; printf '{}' > "$K/source/manifest.json"; printf '{}' > "$K/latest.json"; printf 'V1' > "$K/files/iw4x.exe"   # v1.x leftovers
    cp "$KIT0/iw4x32_update.py" "$KIT0/iw4x32_update.ps1" "$K/"
    if [ "$IMPL" = py ]; then IW4X32_GAME="$GAME" python3 "$K/iw4x32_update.py" --play </dev/null >"$R/9.out" 2>&1; rc=$?
        [ $rc = 20 ] && ok "v2.0 shim exits 20 (the old play-linux.sh stops)" || bad "v2.0 shim exit $rc"
    else "$PWSH" -NoProfile -NonInteractive -File "$K/iw4x32_update.ps1" --play </dev/null >"$R/9.out" 2>&1; fi
    [ ! -e "$K/Play IW4x-32.bat" ] && [ ! -e "$K/server" ] && [ ! -e "$K/iw4x32_update.py" ] && ok "migration: the old scripts are gone" || bad "migration: old files left"
    [ -f "$K/files/backup/iw4x.dll" ] && [ ! -e "$K/backup" ] && ok "migration: backup/ moved into files/" || bad "migration: backup not moved"
    [ ! -e "$K/source" ] && [ ! -e "$K/latest.json" ] && [ ! -e "$K/files/iw4x.exe" ] && ok "migration: v1.x leftovers gone" || bad "migration: v1.x leftovers left"
    has "$R/9.out" "command:" "migration: the game starts"

    # 10. uninstall
    IW4X32_YES=1 run "$K" "$R/10.out" --uninstall
    [ "$(cat "$GAME/iw4x.dll")" = "$OFF" ] && ok "uninstall: the official dll is back" || bad "uninstall: dll not restored"
    if [ "$IMPL" = py ]; then [ ! -f "$R/xdg/applications/iw4x32.desktop" ] && ok "uninstall: menu entry removed" || bad "uninstall: menu entry left"; fi

    # 10b. a crashed game's leftovers (SteamAppId=10190 in their environment) are closed; a server never (py)
    if [ "$IMPL" = py ]; then
        if grep -lzs '^SteamAppId=10190$' /proc/[0-9]*/environ >/dev/null 2>&1; then
            echo "  skip --fix test: a real MW2 process runs on this machine"
        else
            env SteamAppId=10190 sleep 300 & LEFT=$!
            env SteamAppId=10190 python3 -c 'import time; time.sleep(300)' -dedicated & SRV=$!
            sleep 0.5
            IW4X32_GAME="$GAME" python3 "$K/files/iw4x32.py" --fix </dev/null >"$R/10b.out" 2>&1
            sleep 0.3
            kill -0 $LEFT 2>/dev/null && bad "--fix: a leftover game process is still there" || ok "--fix: leftover closed"
            kill -0 $SRV 2>/dev/null && ok "--fix: a dedicated server is left alone" || bad "--fix killed a server"
            kill $LEFT $SRV 2>/dev/null; wait $LEFT $SRV 2>/dev/null
            IW4X32_GAME="$GAME" python3 "$K/files/iw4x32.py" --fix </dev/null >"$R/10c.out" 2>&1
            has "$R/10c.out" "nothing of the game is running" "--fix: nothing left says so"
        fi
    fi

    # 11. only the launcher downloaded: it fetches the release itself
    G2=$R/game2; fake_game "$G2"
    if [ "$IMPL" = py ]; then mkdir -p "$R/boot"; cp "$KIT0/IW4x-32.sh" "$R/boot/"
        sh "$R/boot/IW4x-32.sh" --setup "$G2" </dev/null >"$R/11.out" 2>&1
    else mkdir -p "$R/boot/IW4x-32/files"; cp "$KIT0/files/iw4x32.ps1" "$R/boot/IW4x-32/files/"
        run "$R/boot/IW4x-32" "$R/11.out" --setup "$G2"; fi
    [ -f "$G2/IW4x-32/files/iw4x.dll" ] && [ -f "$G2/IW4x-32/README.txt" ] && ok "bootstrap: the whole release was fetched and set up" || bad "bootstrap: kit missing"
    same "$G2/iw4x.dll" "$KIT0/files/iw4x.dll" "bootstrap: IW4x-32 is installed"
done
echo
echo "kit_test: $PASS passed, $FAIL failed   (tree: $T)"
[ "$FAIL" = 0 ]
