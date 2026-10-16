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

echo "== server start before install: must refuse =="
out=$(bash "$KIT/start-server-linux.sh" --dry 2>&1 || true)
echo "$out" | grep -q "not installed" && [ ! -e "$GAME/userraw/server_iw4x32.cfg" ] \
    && echo "  OK   server refuses a game without IW4x-32" || echo "  FAIL server start without install: $out"

echo "== install: official dll in place, v1.x iw4x.exe left over =="
run_sh install-linux.sh
echo "== server start after install (dry run, port 28961) =="
out=$(bash "$KIT/start-server-linux.sh" --dry 28961 2>&1 || true)
echo "$out" | grep -q "net_port 28961" && echo "$out" | grep -q "sv_maxclients 32" && echo "$out" | grep -q "+exec server_iw4x32.cfg" \
    && echo "  OK   server command: port 28961, 32 slots, its settings file" || echo "  FAIL server command: $out"
same "$GAME/userraw/server_iw4x32.cfg" "$KIT/server/server_iw4x32.cfg" "server settings made in userraw/"
printf '// edited\n' >> "$GAME/userraw/server_iw4x32.cfg"; bash "$KIT/start-server-linux.sh" --dry >/dev/null 2>&1
grep -q "// edited" "$GAME/userraw/server_iw4x32.cfg" && echo "  OK   a second start keeps the edited settings" || echo "  FAIL settings overwritten"
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

# ---- setup-linux.sh: the one-click path. A fake Steam install (two libraries, MW2 in the second one from
# libraryfolders.vdf), no IW4x at all, and a FAKE official IW4x launcher behind a file:// "GitHub release" that
# writes the official iw4x.dll when it is run. Nothing here touches the network or a real game.
echo "== setup: finds MW2 in a Steam library, installs official IW4x + IW4x-32, makes 4 shortcuts =="
H=$T/home; LIB2=$T/lib2; MW2="$LIB2/steamapps/common/Call of Duty Modern Warfare 2"
mkdir -p "$H/.steam/steam/steamapps/common/Counter-Strike" "$MW2" "$T/zip" "$T/launcher/pkg"
printf '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' "$LIB2" > "$H/.steam/steam/steamapps/libraryfolders.vdf"
printf 'PLAIN-MW2' > "$MW2/iw4mp.exe"
cp -a "$KIT"/. "$T/zip/IW4x-32" && rm -rf "$T/zip/IW4x-32/backup"     # the zip as a player extracts it
printf '#!/bin/sh\nprintf "OFFICIAL-DLL-CONTENT" > "$PWD/iw4x.dll"\nprintf "%%s\\n" "$*" > "$PWD/launcher-args.txt"\n' \
    > "$T/launcher/pkg/iw4x-launcher"; chmod +x "$T/launcher/pkg/iw4x-launcher"
tar -cJf "$T/launcher/iw4x-launcher.tar.xz" -C "$T/launcher/pkg" iw4x-launcher
printf '{"tag_name":"r9999","assets":[{"name":"iw4x-launcher-x86_64-linux-glibc.tar.xz","browser_download_url":"file://%s","digest":"sha256:%s"}]}\n' \
    "$T/launcher/iw4x-launcher.tar.xz" "$(sha256sum "$T/launcher/iw4x-launcher.tar.xz" | cut -d' ' -f1)" \
    > "$T/launcher-release.json"
export IW4X32_LAUNCHER_RELEASE_URL="file://$T/launcher-release.json"
setup() { ( cd "$T/zip/IW4x-32" && HOME="$1" XDG_DATA_HOME="$1/.local/share" bash setup-linux.sh "${@:2}" </dev/null 2>&1 ); }
out=$(setup "$H"); echo "$out" | grep -q "^  exit=" && echo "$out"
echo "$out" | grep -qF "Found Modern Warfare 2: $MW2" && echo "  OK   setup found MW2 in the second library" \
    || echo "  FAIL setup did not find MW2: $out"
grep -q -- "--skip-launch" "$MW2/launcher-args.txt" 2>/dev/null \
    && echo "  OK   the official IW4x launcher was run with --skip-launch (install/update only)" \
    || echo "  FAIL the official launcher did not run: $out"
same "$MW2/iw4x-launcher" "$T/launcher/pkg/iw4x-launcher" "the official launcher was downloaded into the game folder"
same "$MW2/IW4x-32/install-linux.sh" "$KIT/install-linux.sh" "the kit was copied into the game folder"
same "$MW2/iw4x.dll" "$V/ours.dll" "setup installed IW4x-32"
same "$MW2/IW4x-32/backup/iw4x.dll" "$V/official.dll" "backup holds the official dll the fake launcher wrote"
n=$(ls "$H/.local/share/applications"/iw4x32-*.desktop 2>/dev/null | wc -l)
[ "$n" = 4 ] && grep -q -- "--play" "$H/.local/share/applications/iw4x32-play.desktop" \
    && grep -q -- "--vanilla-server" "$H/.local/share/applications/iw4x32-vanilla-server.desktop" \
    && echo "  OK   4 .desktop entries (play, vanilla, server, vanilla server)" || echo "  FAIL shortcuts: $n file(s)"

echo "== setup --no-shortcuts: nothing in ~/.local/share/applications =="
rm -rf "$MW2/IW4x-32" "$MW2/iw4x.dll" "$MW2/iw4x-launcher" "$MW2/launcher-args.txt" "$H/.local/share"
out=$(setup "$H" --no-shortcuts)
same "$MW2/iw4x.dll" "$V/ours.dll" "still installs without shortcuts"
n=$(ls "$H/.local/share/applications"/iw4x32-*.desktop 2>/dev/null | wc -l)
[ "$n" = 0 ] && echo "  OK   no .desktop entries written" || echo "  FAIL $n .desktop file(s) with --no-shortcuts"

echo "== setup with a launcher download that is not what the release says: must refuse it =="
rm -rf "$MW2/IW4x-32" "$MW2/iw4x.dll" "$MW2/iw4x-launcher" "$MW2/launcher-args.txt"
sed -i 's/"digest":"sha256:[0-9a-f]*/"digest":"sha256:0000000000000000000000000000000000000000000000000000000000000000/' "$T/launcher-release.json"
out=$(setup "$H")
echo "$out" | grep -qi "download check failed" && echo "  OK   a launcher download with the wrong digest is refused" \
    || echo "  FAIL the digest was not checked: $out"
[ ! -e "$MW2/iw4x.dll" ] && echo "  OK   nothing was installed over a bad download" || echo "  FAIL it installed anyway"
sed -i "s|\"digest\":\"sha256:[0-9a-f]*\"|\"digest\":\"sha256:$(sha256sum "$T/launcher/iw4x-launcher.tar.xz" | cut -d' ' -f1)\"|" "$T/launcher-release.json"

echo "== setup with no MW2 anywhere: asks, Enter stops with nothing changed =="
mkdir -p "$T/emptyhome"
out=$(setup "$T/emptyhome")
echo "$out" | grep -qi "could not find Modern Warfare 2" && echo "  OK   it asks when it finds nothing" || echo "  FAIL: $out"
echo "$out" | grep -q "Nothing was changed" && [ ! -e "$T/emptyhome/.local/share" ] \
    && echo "  OK   Enter stops with nothing changed" || echo "  FAIL Enter changed something"

echo "== launcher: the menu takes Enter = the last choice, and the modes print their command =="
out=$(cd "$MW2/IW4x-32" && IW4X32_GAME="$MW2" bash launcher-linux.sh --server --dry 28961 2>&1)
echo "$out" | grep -q "sv_maxclients 32" && echo "$out" | grep -q "net_port 28961" \
    && echo "  OK   --server --dry: 32 slots on the port asked for" || echo "  FAIL --server --dry: $out"
out=$(cd "$MW2/IW4x-32" && IW4X32_GAME="$MW2" bash launcher-linux.sh --vanilla-server --dry 28962 2>&1)
echo "$out" | grep -q "sv_maxclients 18" && echo "$out" | grep -q "+exec server_vanilla.cfg" \
    && echo "  OK   --vanilla-server --dry: 18 slots, its own settings file" || echo "  FAIL --vanilla-server --dry: $out"
same "$MW2/userraw/server_vanilla.cfg" "$KIT/server/server_vanilla.cfg" "userraw/server_vanilla.cfg made"
printf 'server\n' > "$MW2/IW4x-32/mode.txt"
out=$(cd "$MW2/IW4x-32" && IW4X32_GAME="$MW2" bash launcher-linux.sh --dry < /dev/null 2>&1)
echo "$out" | grep -q "sv_maxclients 32" && echo "  OK   no mode given: Enter takes what was started last time"
printf 'vanilla-server\n' > "$MW2/IW4x-32/mode.txt"
out=$(cd "$MW2/IW4x-32" && IW4X32_GAME="$MW2" bash launcher-linux.sh --dry < /dev/null 2>&1)
echo "$out" | grep -q "sv_maxclients 18" && echo "  OK   mode.txt is remembered for the next start" \
    || echo "  FAIL remembered mode ignored: $out"
grep -q "^server$" "$MW2/IW4x-32/mode.txt" || true

echo "test tree: $T"
