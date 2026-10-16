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
# re-running says "already installed"; uninstall puts the official files back. The launcher is then run for
# real: its four modes, the menu (no "choice" program under Wine -> the set /p fallback), what is remembered in
# mode.txt, and "IW4x-32 Setup.bat" setting a second game folder up from a folder the player extracted.
# PowerShell is a stub under Wine, so --dry is used for the paths that would start a game: they must print the
# command without needing PowerShell.
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

# ---- the launcher: the same four modes as launcher-linux.sh, and the menu ------------------------------------
echo "== launcher --server / --vanilla-server / --play (dry) =="
out=$( cd "$KIT" && wine cmd /c call "IW4x-32 Launcher.bat" --server --dry 28961 2>&1 || true )
echo "$out" | grep -q "sv_maxclients 32" && echo "$out" | grep -q "net_port 28961" \
    && echo "  OK   --server --dry: 32 slots on the port asked for" || echo "  FAIL --server --dry: $out"
out=$( cd "$KIT" && wine cmd /c call "IW4x-32 Launcher.bat" --vanilla-server --dry 28962 2>&1 || true )
echo "$out" | grep -q "sv_maxclients 18" && echo "$out" | grep -q "+exec server_vanilla.cfg" \
    && echo "  OK   --vanilla-server --dry: 18 slots, its own settings file" || echo "  FAIL --vanilla-server --dry: $out"
same "$GAME/userraw/server_vanilla.cfg" "$KIT/server/server_vanilla.cfg" "userraw/server_vanilla.cfg made"
out=$( cd "$KIT" && wine cmd /c call "IW4x-32 Launcher.bat" --play --dry +connect nowhere 2>&1 || true )
echo "$out" | grep -q "iw4x.exe" && echo "$out" | grep -q "+connect nowhere" \
    && echo "  OK   --play --dry: the game command with the arguments that were given" || echo "  FAIL --play --dry: $out"

echo "== launcher menu: no mode given (no choice program here -> the set /p fallback) =="
rm -f "$KIT/mode.txt"
out=$( cd "$KIT" && printf '3\n' | wine cmd /c call "IW4x-32 Launcher.bat" --dry 2>&1 || true )
echo "$out" | grep -q "\[1\] IW4x-32" && echo "$out" | grep -q "\[4\] IW4x server" \
    && echo "  OK   the menu lists all four" || echo "  FAIL menu: $out"
echo "$out" | grep -q "sv_maxclients 32" && grep -q "^server$" "$KIT/mode.txt" 2>/dev/null \
    && echo "  OK   3 starts the server and is remembered in mode.txt" || echo "  FAIL menu answer 3: $out"
out=$( cd "$KIT" && printf '\n' | wine cmd /c call "IW4x-32 Launcher.bat" --dry 2>&1 || true )
echo "$out" | grep -q "sv_maxclients 32" \
    && echo "  OK   Enter takes what was started last time" || echo "  FAIL Enter: $out"
printf 'vanilla-server\n' > "$KIT/mode.txt"
out=$( cd "$KIT" && printf '\n' | wine cmd /c call "IW4x-32 Launcher.bat" --dry 2>&1 || true )
echo "$out" | grep -q "sv_maxclients 18" \
    && echo "  OK   the remembered mode is the default" || echo "  FAIL remembered mode: $out"

echo "== setup: a second game folder, set up from an extracted folder =="
G2=$T/game2; ZIP=$T/zip/IW4x-32
mkdir -p "$G2" "$ZIP"
cp -a "$KIT"/. "$ZIP"; rm -rf "$ZIP/backup" "$ZIP/mode.txt" "$ZIP/userraw"   # the zip as a player extracts it
printf 'PLAIN-MW2' > "$G2/iw4mp.exe"
printf 'OFFICIAL-DLL-CONTENT' > "$G2/iw4x.dll"
printf 'official-exe-backup' > "$G2/iw4x.exe"
out=$( cd "$T/zip" && printf '\n' | wine cmd /c call "IW4x-32 Setup.bat" "$(winepath -w "$G2")" --no-shortcuts 2>&1 || true )
echo "$out" | grep -q "IW4x-32 is set up" && echo "  OK   setup finished" || echo "  FAIL setup: $out"
same "$G2/IW4x-32/Install IW4x-32.bat" "$KIT/Install IW4x-32.bat" "the kit was copied into the game folder"
same "$G2/iw4x.dll" "$V/ours.dll" "setup installed IW4x-32"
same "$G2/IW4x-32/backup/iw4x.dll" "$V/official.dll" "backup holds the official dll"

echo "== setup with a folder that is not the game: stops, changes nothing =="
out=$( cd "$T/zip" && printf '\n' | wine cmd /c call "IW4x-32 Setup.bat" "$(winepath -w "$T/notagame")" --no-shortcuts 2>&1 || true )
echo "$out" | grep -qi "no iw4mp.exe" && [ ! -e "$T/notagame" ] \
    && echo "  OK   a folder without the game is refused" || echo "  FAIL bad game folder: $out"

echo "test tree: $T"
