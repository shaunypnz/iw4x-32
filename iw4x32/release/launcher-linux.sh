#!/usr/bin/env bash
# IW4x-32 launcher (Linux) - the one script that starts everything; the shortcuts point here.
#
#   bash launcher-linux.sh                   ask what to start (1-4, Enter = what you started last time)
#   bash launcher-linux.sh --play            IW4x-32 - 32-player servers (and normal ones)
#   bash launcher-linux.sh --vanilla         vanilla IW4x - the official IW4x, always the latest version
#   bash launcher-linux.sh --server [port]   a 32-player dedicated server (port 28960)
#   bash launcher-linux.sh --vanilla-server [port]   a normal 18-player IW4x dedicated server
#
#   --dry / --dry-run   only check the install and print the command
#   --no-update         skip the version check (also: IW4X32_NO_UPDATE=1)
#   --direct            --play in a Steam library: run iw4x.exe with the game's Proton, without Steam's launcher
#   anything else goes to the game, e.g.  +connect <server address>
#
# Before it starts anything it checks GitHub (5 s each, no network = just start): a new IW4x-32 release is
# installed, an IW4x older than what IW4x-32 is made for is updated with the OFFICIAL IW4x launcher, and a newer
# IW4x only prints a warning - IW4x-32 always starts (iw4x32_update.py does that work, same as on Windows).
# What you picked is remembered in IW4x-32/mode.txt. "play-linux.sh" and "start-server-linux.sh" are thin
# wrappers of this file, so old shortcuts and old habits keep working.
#
# Steam (Proton) installs: the game must run through Steam's Proton, inside the game's own Proton prefix
# (steamapps/compatdata/10190). The reliable way - set this ONCE in Steam -> "Call of Duty: Modern Warfare 2 -
# Multiplayer" -> Properties -> Launch Options:
#
#     bash -c 'exec "${@/iw4mp.exe/iw4x.exe}"' -- %command%
#
# (Steam then starts iw4x.exe instead of iw4mp.exe, with its own Proton, runtime and prefix.) After that just
# press Play in Steam, or run this script: it checks the launch option and asks Steam to start the game.
set -euo pipefail
OURS_DLL=f0a247ff84e1307330d43a03c4e8e4f8b8f921a465c6206e0b14a825f736a2d1
LAUNCH_OPTION='bash -c '"'"'exec "${@/iw4mp.exe/iw4x.exe}"'"'"' -- %command%'
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAME="${IW4X32_GAME:-$(dirname "$KIT")}"
MODE=""; MODE_SET=0; PORT=28960; DRY=0; NOUPD=0; DIRECT=0; ARGS=(); ORIG=("$@")
for a in "$@"; do
    case "$a" in
        --play|--iw4x32)     MODE=iw4x32; MODE_SET=1 ;;
        --vanilla)           MODE=vanilla; MODE_SET=1 ;;
        --server)            MODE=server; MODE_SET=1 ;;
        --vanilla-server)    MODE=vanilla-server; MODE_SET=1 ;;
        --dry|--dry-run)     DRY=1 ;;
        --no-update)         NOUPD=1 ;;
        --direct)            DIRECT=1 ;;
        ''|*[!0-9]*)         ARGS+=("$a") ;;
        *)                   PORT="$a" ;;
    esac
done
[ "$NOUPD" = 1 ] && export IW4X32_NO_UPDATE=1
sha() { [ -f "$1" ] && sha256sum "$1" | cut -d' ' -f1 || echo none; }
run() { if [ "$DRY" = 1 ]; then printf '%q ' "$@"; echo; else "$@"; fi }
flag_of() { case "$1" in iw4x32) echo --play ;; vanilla) echo --vanilla ;; server) echo --server ;;
                        vanilla-server) echo --vanilla-server ;; esac; }
read_mode() {
    local m
    m=$(head -1 "$KIT/mode.txt" 2>/dev/null | tr -d ' \t\r\n' || true)
    case "$m" in vanilla|server|vanilla-server) echo "$m" ;; *) echo iw4x32 ;; esac
}
write_mode() { printf '%s\n' "$1" > "$KIT/mode.txt" 2>/dev/null || true; }

# ---- what to start: a flag, IW4X32_MODE, the menu (5 s, Enter = last choice), or what is remembered ----------
PICK=""
menu() {
    echo "Start what?"
    echo "  [1] IW4x-32  - 32-player servers (and normal ones)"
    echo "  [2] Vanilla IW4x - the official IW4x, always the latest version"
    echo "  [3] IW4x-32 server - 32-player dedicated server (port $PORT)"
    echo "  [4] IW4x server - normal 18-player dedicated server (port $PORT)"
    printf 'Enter = %s (starts in 5 s): ' "$1"
    local line=""
    read -t 5 -r line || true
    echo
    case "${line:-$1}" in
        1|iw4x32) PICK=iw4x32 ;; 2|vanilla) PICK=vanilla ;; 3|server) PICK=server ;;
        4|vanilla-server) PICK=vanilla-server ;; *) PICK="$1" ;;
    esac
}
if [ -z "$MODE" ]; then
    case "${IW4X32_MODE:-}" in iw4x32|vanilla|server|vanilla-server) MODE="$IW4X32_MODE"; MODE_SET=1 ;; esac
fi
if [ -z "$MODE" ]; then
    LAST=$(read_mode)
    if [ "${IW4X32_NO_MENU:-0}" != 1 ] && [ -t 0 ]; then menu "$LAST"; MODE="$PICK"; MODE_SET=1; else MODE="$LAST"; fi
fi
[ "$MODE_SET" = 1 ] && write_mode "$MODE"

# ---- the version check (iw4x32_update.py: both GitHub repos, 5 s each, nothing without network) --------------
# exit 10 = this kit was updated -> run the new launcher; 20 = vanilla IW4x was started by its launcher -> stop
check() {   # $1 = --iw4x32 / --vanilla / --restore-official
    [ "$DRY" = 1 ] && return 0
    command -v python3 >/dev/null || return 0
    rc=0; IW4X32_GAME="$GAME" IW4X32_KEEP_MODE=1 IW4X32_NO_MENU=1 python3 "$KIT/iw4x32_update.py" "$1" || rc=$?
    [ "$rc" = 20 ] && exit 0
    [ "$rc" = 10 ] && exec bash "$KIT/launcher-linux.sh" "$(flag_of "$MODE")" --no-update "${ORIG[@]}"
    return 0
}
case "$MODE" in
    vanilla)
        if [ "$DRY" = 1 ]; then
            echo "  command:     $GAME/iw4x-launcher (the official IW4x launcher: updates IW4x and starts the game)"
            exit 0
        fi
        check --vanilla
        echo "IW4x-32: vanilla IW4x did not start - is the official IW4x launcher in $GAME?"; exit 1 ;;
    vanilla-server) check --restore-official ;;
    *) check --iw4x32 ;;
esac

# ---- a dedicated server -------------------------------------------------------------------------------------
start_server() {   # $1 = sv_maxclients, $2 = the userraw settings file to make and exec, $3 = what to call it
    local slots="$1" cfg="$2" label="$3"
    [ -f "$GAME/iw4x.exe" ] || { echo "ERROR: no iw4x.exe in $GAME - put the IW4x-32 folder INSIDE your MW2/IW4x game folder."; exit 1; }
    if [ "$slots" = 32 ] && [ "$(sha "$GAME/iw4x.dll")" != "$OURS_DLL" ]; then
        echo "ERROR: IW4x-32 is not installed in $GAME (its iw4x.dll is not the IW4x-32 one). Run ./install-linux.sh first."
        exit 1
    fi
    mkdir -p "$GAME/userraw"
    if [ ! -f "$GAME/userraw/$cfg" ]; then
        cp "$KIT/server/$cfg" "$GAME/userraw/$cfg" || exit 1
        echo "Made userraw/$cfg - edit it to name your server and set an rcon password."
    fi
    set -- -dedicated -stdout +set net_port "$PORT" +exec "$cfg" +set sv_maxclients "$slots" \
        +set party_maxplayers "$slots" +set party_enable 0 +map_rotate
    echo "$label"
    echo "  game folder: $GAME"
    echo "  port:        $PORT (UDP)"
    echo "  command:     wine iw4x.exe $*"
    [ "$DRY" = 1 ] && exit 0
    command -v wine >/dev/null 2>&1 || { echo "ERROR: wine is not installed (Debian/Ubuntu: sudo apt install wine)."; exit 1; }
    cd "$GAME" || exit 1
    export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-iw4x32-server}" WINEDEBUG=-all
    exec wine iw4x.exe "$@"
}

# ---- IW4x-32: start the game the way the official IW4x launcher does, minus its file check --------------------
start_play() {
    # what the official IW4x launcher does before it starts the game: without this Steam takes over and starts normal MW2
    steam_appid() { [ "$DRY" = 1 ] || [ -f "$GAME/steam_appid.txt" ] || printf '10190\r\n' > "$GAME/steam_appid.txt"; }
    [ -f "$GAME/iw4x.exe" ] || { echo "iw4x.exe not found in $GAME - is the IW4x-32 folder inside your game folder?"; exit 1; }
    case "$GAME" in
        */steamapps/common/*) LIB="${GAME%%/steamapps/common/*}/steamapps" ;;
        *) LIB="" ;;
    esac
    if [ -z "$LIB" ]; then                                   # not a Steam library: plain Wine
        command -v wine >/dev/null || { echo "wine is not installed (sudo apt install wine)."; exit 1; }
        cd "$GAME"
        echo "Starting iw4x.exe with Wine (prefix: ${WINEPREFIX:-~/.wine})"
        steam_appid
        run env SteamAppId=10190 SteamGameId=10190 wine iw4x.exe "${ARGS[@]}"
        exit 0
    fi

    # ---- Steam library --------------------------------------------------------------------------------------
    APPID=""; COMPAT=""
    for id in 10190 10180; do
        if [ -d "$LIB/compatdata/$id/pfx" ]; then APPID=$id; COMPAT="$LIB/compatdata/$id"; break; fi
    done
    if [ -z "$COMPAT" ]; then
        echo "No Proton prefix for MW2 in $LIB/compatdata (10190 or 10180)."
        echo "Start 'Modern Warfare 2 - Multiplayer' once from Steam (with Proton), close it, then run this again."
        exit 1
    fi

    # Steam client folder (native, Snap, Flatpak) - the one that owns this library's Proton
    STEAM_DIR=""
    for d in "$HOME/.steam/steam" "$HOME/.local/share/Steam" "$HOME/snap/steam/common/.local/share/Steam" \
             "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam"; do
        [ -d "$d/userdata" ] && { STEAM_DIR="$(cd "$d" && pwd -P)"; break; }
    done

    launch_option_set() {
        [ -n "$STEAM_DIR" ] || return 1
        python3 - "$STEAM_DIR" "$APPID" <<'PY'
import glob, re, sys
steam, appid = sys.argv[1], sys.argv[2]
for f in glob.glob(f"{steam}/userdata/*/config/localconfig.vdf"):
    t = open(f, errors="replace").read()
    for m in re.finditer(r'"%s"\s*\{' % appid, t):
        depth, i = 1, m.end()
        while i < len(t) and depth:
            depth += {"{": 1, "}": -1}.get(t[i], 0)
            i += 1
        block = t[m.end():i]
        lo = re.search(r'"LaunchOptions"\s*"((?:[^"\\]|\\.)*)"', block)
        if lo and "iw4x.exe" in lo.group(1):
            sys.exit(0)
sys.exit(1)
PY
    }

    if [ "$DIRECT" = 0 ]; then
        if launch_option_set; then
            echo "Steam launch option found - asking Steam to start Modern Warfare 2 - Multiplayer (iw4x.exe, Proton)."
            if command -v steam >/dev/null; then run steam -applaunch "$APPID" "${ARGS[@]}"
            else run xdg-open "steam://rungameid/$APPID"; fi
            exit 0
        fi
        echo "To run IW4x-32 inside Steam's Proton prefix, set this ONCE in Steam:"
        echo "  Modern Warfare 2 - Multiplayer -> Properties -> Launch Options:"
        echo
        echo "    $LAUNCH_OPTION"
        echo
        echo "then press Play in Steam (or run this script again)."
        echo "Or run it right now without Steam's launcher:  bash launcher-linux.sh --play --direct"
        exit 1
    fi

    # --direct: the game's Proton (from compatdata/<appid>/config_info) + the game's prefix
    PROTON_DIR="$(grep -m1 -E '/share/fonts/?$' "$COMPAT/config_info" 2>/dev/null | sed -E 's#/(files|dist)/share/fonts/?$##' || true)"
    [ -x "$PROTON_DIR/proton" ] || { echo "Could not find this game's Proton (from $COMPAT/config_info). Use the Steam launch option instead."; exit 1; }
    if [ -z "$STEAM_DIR" ]; then
        case "$PROTON_DIR" in */steamapps/common/*) STEAM_DIR="${PROTON_DIR%%/steamapps/common/*}" ;; esac
    fi
    echo "Starting iw4x.exe with $(head -1 "$COMPAT/config_info") in $COMPAT"
    cd "$GAME"
    steam_appid
    # shellcheck disable=SC2086
    run env STEAM_COMPAT_DATA_PATH="$COMPAT" STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_DIR:-$HOME/.steam/steam}" \
        SteamAppId="$APPID" SteamGameId="$APPID" "$PROTON_DIR/proton" run "$GAME/iw4x.exe" "${ARGS[@]}"
}

case "$MODE" in
    iw4x32) start_play ;;
    server) start_server 32 server_iw4x32.cfg "IW4x-32 server" ;;
    vanilla-server) start_server 18 server_vanilla.cfg "IW4x server (vanilla, 18 players)" ;;
esac
