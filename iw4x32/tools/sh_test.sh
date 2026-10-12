#!/usr/bin/env bash
# sh_test.sh - run the kit's Linux installers (install-linux.sh / uninstall-linux.sh) against a fake game folder.
# Same cases as bat_test.sh (which covers the Windows .bat side under Wine): official dll is checked and backed
# up, only files/iw4x.dll is installed, a v1.x iw4x.exe is restored from backup/, a modded dll is refused, a
# missing v1.x backup stops without changing anything, uninstall restores the official files.
# Usage: bash iw4x32/tools/sh_test.sh        (test tree left under .scratch/, printed at the end)
set -euo pipefail
KIT_SRC=${KIT_SRC:-iw4x32/release}
T=$(mktemp -d "$PWD/.scratch/sh-test.XXXX")
GAME=$T/game; KIT=$T/game/IW4x-32; V=$T/reference
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

# the hash constants in the scripts must describe our fake official / v1.x files
sed -i "s/^V1_EXE=[0-9a-f]*/V1_EXE=$(sha256sum "$V/v1.exe" | cut -d' ' -f1)/;
        s/^OFFICIAL_EXE=[0-9a-f]*/OFFICIAL_EXE=$(sha256sum "$V/official.exe" | cut -d' ' -f1)/;
        s/^OFFICIAL_DLL=[0-9a-f]*/OFFICIAL_DLL=$(sha256sum "$V/official.dll" | cut -d' ' -f1)/" "$KIT"/*.sh

# the installers refuse to touch a running game (pgrep -x iw4x.exe) - a test run must not depend on what the
# machine happens to have started, so a pgrep that reports "nothing running" goes first on PATH
mkdir -p "$T/bin"; printf '#!/bin/sh\nexit 1\n' > "$T/bin/pgrep"; chmod +x "$T/bin/pgrep"
export PATH="$T/bin:$PATH"

run_sh() { local s="$1"; [ -f "$s" ] || s="$KIT/$s"; bash "$s" || echo "  exit=$?"; }
same() { cmp -s "$1" "$2" && echo "  OK   $3" || echo "  FAIL $3"; }

echo "== install: official dll in place, v1.x iw4x.exe left over =="
run_sh install-linux.sh
same "$GAME/iw4x.dll" "$V/ours.dll" "game iw4x.dll is ours (files/iw4x.dll)"
same "$GAME/iw4x.exe" "$V/official.exe" "game iw4x.exe restored from backup/"
same "$KIT/backup/iw4x.dll" "$V/official.dll" "backup holds the official dll"

echo "== install again: already installed =="
run_sh install-linux.sh
same "$GAME/iw4x.dll" "$V/ours.dll" "still ours"

echo "== uninstall: official files back =="
run_sh uninstall-linux.sh
same "$GAME/iw4x.dll" "$V/official.dll" "game iw4x.dll is the official one"
same "$GAME/iw4x.exe" "$V/official.exe" "game iw4x.exe is the official one"

echo "== install with a modded dll: must stop and change nothing =="
printf 'SOME-MOD' > "$GAME/iw4x.dll"
run_sh install-linux.sh
same "$GAME/iw4x.dll" "$V/mod.dll" "modded dll untouched"

echo "== install with no backup of the v1.x exe: must stop and change nothing =="
printf 'V1-EXE-CONTENT' > "$GAME/iw4x.exe"
printf 'OFFICIAL-DLL-CONTENT' > "$GAME/iw4x.dll"
rm -f "$KIT/backup/iw4x.exe"
run_sh install-linux.sh
same "$GAME/iw4x.dll" "$V/official.dll" "nothing installed"
same "$GAME/iw4x.exe" "$V/v1.exe" "v1.x exe left alone"

echo "== install in a folder with no game: must stop =="
mkdir -p "$T/nogame/IW4x-32" && cp -a "$KIT"/. "$T/nogame/IW4x-32"
run_sh "$T/nogame/IW4x-32/install-linux.sh"

echo "test tree: $T"
