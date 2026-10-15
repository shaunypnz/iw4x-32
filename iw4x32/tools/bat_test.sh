#!/usr/bin/env bash
# bat_test.sh - run the kit's Windows installers under Wine cmd, against a fake game folder.
#
# Wine's certutil.exe (and fc.exe) are stubs that print nothing, so the installers' SHA-256 checks cannot be
# exercised under Wine as-is: this compiles iw4x32/tools/mini_certutil.c with the same MSVC the project uses and
# puts it in the kit folder as certutil.exe - cmd looks in the current directory first, so the installers hash
# for real. Everything else is stock Wine cmd: the .bat files run exactly as they do on a player's Windows.
#
# Proves: install checks the official dll, backs it up, installs only files/iw4x.dll, restores a v1.x iw4x.exe
# from backup/ and stops without changing anything when that backup is missing; a modded dll is refused;
# re-running says "already installed"; uninstall puts the official files back.
#
# Usage: bash iw4x32/tools/bat_test.sh        (needs wine + ~/.msvc; test tree left under .scratch/)
set -euo pipefail
KIT_SRC=${KIT_SRC:-iw4x32/release}
export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-msvc}" WINEDEBUG=-all XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/xdg}"
mkdir -p "$XDG_RUNTIME_DIR"
T=$(mktemp -d "$PWD/.scratch/bat-test.XXXX")
GAME=$T/game; KIT=$T/game/IW4x-32   # the kit lives INSIDE the game folder, like it does for players
V=$T/reference
mkdir -p "$GAME" "$KIT/backup" "$V"
cp -a "$KIT_SRC"/. "$KIT"
rm -f "$KIT/mode.txt"

printf 'OFFICIAL-DLL-CONTENT' > "$GAME/iw4x.dll"
printf 'V1-EXE-CONTENT' > "$GAME/iw4x.exe"          # an IW4x-32 v1.x install left this behind
printf 'official-exe-backup' > "$KIT/backup/iw4x.exe"
printf 'OFFICIAL-DLL-CONTENT' > "$KIT/backup/iw4x.dll"
printf 'SOME-MOD' > "$V/mod.dll"
printf 'OFFICIAL-DLL-CONTENT' > "$V/official.dll"
printf 'V1-EXE-CONTENT' > "$V/v1.exe"
printf 'official-exe-backup' > "$V/official.exe"
cp "$KIT/files/iw4x.dll" "$V/ours.dll"

# the hash constants in the .bat files must describe our fake official / v1.x files
sed -i "s/^set \"V1_EXE=[0-9a-f]*\"/set \"V1_EXE=$(sha256sum "$V/v1.exe" | cut -d' ' -f1)\"/;
        s/^set \"OFFICIAL_EXE=[0-9a-f]*\"/set \"OFFICIAL_EXE=$(sha256sum "$V/official.exe" | cut -d' ' -f1)\"/;
        s/^set \"OFFICIAL_DLL=[0-9a-f]*\"/set \"OFFICIAL_DLL=$(sha256sum "$V/official.dll" | cut -d' ' -f1)\"/" "$KIT"/*.bat

"$HOME/.msvc/bin/x86/cl.exe" /O2 /W3 "$(winepath -w "$PWD/iw4x32/tools/mini_certutil.c")" advapi32.lib \
    "/Fe:$(winepath -w "$KIT/certutil.exe")" "/Fo:$(winepath -w "$T/")" > /dev/null
[ -f "$KIT/certutil.exe" ] || { echo "bat_test: could not build mini_certutil"; exit 1; }

run_bat() {   # the .bat ends in pause: feed it a key
    ( cd "$KIT" && printf '\n' | wine cmd /c "$1" 2>&1 | grep -v '^\s*$' ) || true   # the .bat's exit code is its own business
}
same() { cmp -s "$1" "$2" && echo "  OK   $3" || echo "  FAIL $3"; }

echo "== server start before install: must refuse =="
out=$( cd "$KIT" && wine cmd /c call "Start IW4x-32 Server.bat" --dry 2>&1 || true )
echo "$out" | grep -q "not installed" && [ ! -e "$GAME/userraw/server_iw4x32.cfg" ] \
    && echo "  OK   server refuses a game without IW4x-32" || echo "  FAIL server start without install: $out"

echo "== install: official dll in place, v1.x iw4x.exe left over =="
run_bat "Install IW4x-32.bat"
echo "== server start after install (dry run, port 28961) =="
out=$( cd "$KIT" && wine cmd /c call "Start IW4x-32 Server.bat" --dry 28961 2>&1 || true )
echo "$out" | grep -q "net_port 28961" && echo "$out" | grep -q "sv_maxclients 32" && echo "$out" | grep -q "+exec server_iw4x32.cfg" \
    && echo "  OK   server command: port 28961, 32 slots, its settings file" || echo "  FAIL server command: $out"
same "$GAME/userraw/server_iw4x32.cfg" "$KIT/server/server_iw4x32.cfg" "server settings made in userraw\\"
same "$GAME/iw4x.dll" "$V/ours.dll" "game iw4x.dll is ours (files/iw4x.dll)"
same "$GAME/iw4x.exe" "$V/official.exe" "game iw4x.exe restored from backup/"
same "$KIT/backup/iw4x.dll" "$V/official.dll" "backup holds the official dll"

echo "== install again: already installed =="
run_bat "Install IW4x-32.bat"
same "$GAME/iw4x.dll" "$V/ours.dll" "still ours"

echo "== uninstall: official files back =="
run_bat "Uninstall IW4x-32.bat"
same "$GAME/iw4x.dll" "$V/official.dll" "game iw4x.dll is the official one"
same "$GAME/iw4x.exe" "$V/official.exe" "game iw4x.exe is the official one"

echo "== install with a modded dll: must stop and change nothing =="
printf 'SOME-MOD' > "$GAME/iw4x.dll"
run_bat "Install IW4x-32.bat"
same "$GAME/iw4x.dll" "$V/mod.dll" "modded dll untouched"

echo "== install with no backup of the v1.x exe: must stop and change nothing =="
printf 'V1-EXE-CONTENT' > "$GAME/iw4x.exe"
printf 'OFFICIAL-DLL-CONTENT' > "$GAME/iw4x.dll"
rm -f "$KIT/backup/iw4x.exe"
run_bat "Install IW4x-32.bat"
same "$GAME/iw4x.dll" "$V/official.dll" "nothing installed"
same "$GAME/iw4x.exe" "$V/v1.exe" "v1.x exe left alone"

echo "test tree: $T"
