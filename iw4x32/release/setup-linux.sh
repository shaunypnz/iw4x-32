#!/usr/bin/env bash
# IW4x-32 v2.0 setup (Linux): find your Modern Warfare 2, put the kit in it, install, make shortcuts.
# Run it from wherever you extracted the zip - the kit does NOT have to be inside the game folder yet.
#
#   bash setup-linux.sh                    find MW2 and set everything up
#   bash setup-linux.sh /path/to/MW2       use this game folder
#   bash setup-linux.sh --no-shortcuts     do not make the .desktop entries
#
# What it does, in order:
#   1. finds the MW2 multiplayer folder: this folder's parent when it has iw4mp.exe / iw2mp.exe / iw4x.exe,
#      then your Steam libraries (~/.steam/steam, ~/.local/share/Steam, the Snap and Flatpak ones and every
#      library in their steamapps/libraryfolders.vdf). Several: pick one by number. None: type the path -
#      Enter stops with nothing changed.
#   2. copies this folder to <game>/IW4x-32 (an existing backup\ and mode.txt are kept)
#   3. official IW4x missing or not the version this kit is made for: the OFFICIAL IW4x launcher installs it
#      (downloaded from its GitHub release, checked, run with --skip-launch = install/update only).
#      IW4x-32 never downloads IW4x's own files - the official launcher does that.
#   4. runs install-linux.sh - the same installer you can run by hand, not a copy of it
#   5. makes four entries in ~/.local/share/applications: IW4x-32, vanilla IW4x, and the two servers
#      (--no-shortcuts skips this), then prints what it did.
set -euo pipefail
OFFICIAL_VER=r5168
OFFICIAL_EXE=49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009
OFFICIAL_DLL=e0d8adc473f04f2d0988cffec3ecb8128e9faeba1e169c0acb13118d29aff6ea
OURS_DLL=f0a247ff84e1307330d43a03c4e8e4f8b8f921a465c6206e0b14a825f736a2d1
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MW2="Call of Duty Modern Warfare 2"
NO_SHORTCUTS=0; GAME=""
for a in "$@"; do
    case "$a" in
        --no-shortcuts) NO_SHORTCUTS=1 ;;
        -*) echo "setup-linux.sh: unknown option $a (the only one is --no-shortcuts)"; exit 2 ;;
        *) GAME="$a" ;;
    esac
done
sha() { [ -f "$1" ] && sha256sum "$1" | cut -d' ' -f1 || echo none; }
is_game() { local d="$1"; [ -n "$d" ] && [ -d "$d" ] && \
    { [ -f "$d/iw4mp.exe" ] || [ -f "$d/iw2mp.exe" ] || [ -f "$d/iw4x.exe" ]; }; }

# ---- 1. where is the game? ----------------------------------------------------------------------------------
FOUND=()
add_found() {   # keep a candidate when it really is an MW2 multiplayer folder and is not listed yet
    is_game "$1" || return 0
    local r f
    r=$(cd "$1" 2>/dev/null && pwd -P) || return 0
    for f in "${FOUND[@]:-}"; do [ "$f" = "$r" ] && return 0; done
    FOUND+=("$r")
}
vdf_libraries() {   # the library paths of a libraryfolders.vdf (new format: "path" "X"; old: "0" "X")
    [ -f "$1" ] || return 0
    awk -F'"' '(/"path"[ \t]/ || /^[ \t]*"[0-9]+"[ \t]+"/) { gsub(/\\\\/, "\\", $4); if (length($4)) print $4 }' "$1"
}
steam_libraries() {
    {
        for d in "$HOME/.steam/steam" "$HOME/.local/share/Steam" "$HOME/snap/steam/common/.local/share/Steam" \
                 "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam"; do
            [ -d "$d" ] || continue
            echo "$d"
            vdf_libraries "$d/steamapps/libraryfolders.vdf"
        done
    } | awk 'NF && !seen[$0]++'
}
add_found "$(dirname "$KIT")"                                  # the kit already sits in the game folder
if [ "${#FOUND[@]}" = 0 ]; then
    while read -r lib; do
        [ -d "$lib/steamapps/common" ] || continue
        for d in "$lib/steamapps/common/$MW2"*; do add_found "$d"; done
    done < <(steam_libraries)
fi
if [ -z "$GAME" ]; then
    case "${#FOUND[@]}" in
        0)
            echo "I could not find Modern Warfare 2 (iw4mp.exe) next to this folder or in your Steam libraries."
            printf 'Type the path of your MW2 folder (Enter = stop, nothing is changed): '
            read -r GAME || GAME=""
            [ -n "$GAME" ] || { echo "Nothing was changed."; exit 0; } ;;
        1) GAME="${FOUND[0]}"; echo "Found Modern Warfare 2: $GAME" ;;
        *)
            echo "Found Modern Warfare 2 in more than one place:"
            for i in "${!FOUND[@]}"; do echo "  [$((i + 1))] ${FOUND[$i]}"; done
            printf 'Which one? (Enter = 1, 0 = stop, nothing is changed): '
            read -r n || n=""
            case "$n" in ''|1) GAME="${FOUND[0]}" ;; *[!0-9]*) GAME="" ;;
                *) [ "$n" -ge 1 ] && [ "$n" -le "${#FOUND[@]}" ] && GAME="${FOUND[$((n - 1))]}" || GAME="" ;;
            esac
            [ -n "$GAME" ] || { echo "Nothing was changed."; exit 0; } ;;
    esac
fi
is_game "$GAME" || { echo "ERROR: no iw4mp.exe / iw2mp.exe / iw4x.exe in $GAME - nothing was changed."; exit 1; }
GAME=$(cd "$GAME" && pwd -P)
DEST="$GAME/IW4x-32"

# ---- 2. the kit goes into the game folder --------------------------------------------------------------------
if [ "$DEST" != "$KIT" ]; then
    echo "Copying the IW4x-32 folder to $DEST ..."
    mkdir -p "$DEST" && cp -a "$KIT"/. "$DEST"/ || { echo "ERROR: could not copy to $DEST"; exit 1; }
fi

# ---- 3. official IW4x, with the official launcher ------------------------------------------------------------
need_official=1
case "$(sha "$GAME/iw4x.dll")" in "$OFFICIAL_DLL"|"$OURS_DLL") need_official=0 ;; esac
[ "$(sha "$DEST/backup/iw4x.dll")" = "$OFFICIAL_DLL" ] && need_official=0
if [ "$need_official" = 1 ]; then
    echo "Official IW4x $OFFICIAL_VER is missing here or is another version - the official IW4x launcher fixes that."
    if command -v python3 >/dev/null; then
        IW4X32_GAME="$GAME" python3 "$DEST/iw4x32_update.py" --install-official || true
    else
        echo "  python3 is needed to fetch the official IW4x launcher: start the IW4x launcher once, then run this again."
    fi
    case "$(sha "$GAME/iw4x.dll")" in
        "$OFFICIAL_DLL"|"$OURS_DLL") echo "       OK - official IW4x is in place" ;;
        *) echo "       it is still not the official IW4x $OFFICIAL_VER file - the installer below says what to do" ;;
    esac
fi

# ---- 4. install IW4x-32 (the installer itself does it) --------------------------------------------------------
bash "$DEST/install-linux.sh" || { echo; echo "Setup stopped - see the message above. Nothing else was changed."; exit 1; }

# ---- 5. shortcuts ----------------------------------------------------------------------------------------------
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
desktop() {   # $1 = file, $2 = Name, $3 = Comment, $4 = launcher mode, $5 = Terminal
    cat > "$APPS/$1" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$2
Comment=$3
Exec=bash "$DEST/launcher-linux.sh" $4
Path=$GAME
Terminal=$5
Categories=Game;
StartupNotify=false
EOF
}
if [ "$NO_SHORTCUTS" = 0 ]; then
    mkdir -p "$APPS" || { echo "ERROR: could not write $APPS"; exit 1; }
    desktop iw4x32-play.desktop          "IW4x-32 (32 players)"     "Play IW4x on 32-player servers" --play false
    desktop iw4x32-vanilla.desktop       "IW4x (vanilla)"           "Play the official IW4x" --vanilla false
    desktop iw4x32-server.desktop        "IW4x-32 Server"           "32-player dedicated server" --server true
    desktop iw4x32-vanilla-server.desktop "IW4x Server (vanilla)"   "Normal 18-player dedicated server" --vanilla-server true
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
fi

echo
echo "IW4x-32 is set up."
echo "  game folder: $GAME"
echo "  IW4x-32:     $DEST"
[ "$NO_SHORTCUTS" = 0 ] && echo "  shortcuts:   4 entries in $APPS"
echo
[ "$NO_SHORTCUTS" = 0 ] && echo "Start playing with the \"IW4x-32 (32 players)\" entry, or with:"
echo "    bash \"$DEST/launcher-linux.sh\"            it asks what to start"
echo "Host a 32-player server with the \"IW4x-32 Server\" entry, or with:  bash \"$DEST/start-server-linux.sh\""
case "$GAME" in
    */steamapps/common/*)
        echo
        echo "Steam (Proton), once: Modern Warfare 2 - Multiplayer -> Properties -> Launch Options:"
        echo
        echo "    bash -c 'exec \"\${@/iw4mp.exe/iw4x.exe}\"' -- %command%"
        echo
        echo "  then press Play in Steam: it runs IW4x-32 with the game's own Proton and prefix." ;;
esac
