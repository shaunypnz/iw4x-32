#!/usr/bin/env bash
# Start IW4x-32 on Linux.
#
# Steam (Proton) install - the usual case. The game must run through Steam's Proton, inside the game's own
# Proton prefix (steamapps/compatdata/10190). The reliable way: set this ONCE in Steam ->
# "Call of Duty: Modern Warfare 2 - Multiplayer" -> Properties -> Launch Options:
#
#     bash -c 'exec "${@/iw4mp.exe/iw4x.exe}"' -- %command%
#
# (Steam then starts iw4x.exe instead of iw4mp.exe, with its own Proton, runtime and prefix.) After that just press
# Play in Steam, or run this script: it checks the launch option and asks Steam to start the game.
#
#   bash play-linux.sh            Steam install: start through Steam (after setting the launch option)
#   bash play-linux.sh --direct   Steam install: run iw4x.exe with the game's Proton + prefix, without Steam's
#                                 launcher (Steam should be running; may not work with Snap/Flatpak Steam)
#   bash play-linux.sh --dry-run  only print what would be run
# Not a Steam install: runs iw4x.exe with Wine (set WINEPREFIX if the game has its own prefix).
set -euo pipefail
LAUNCH_OPTION='bash -c '"'"'exec "${@/iw4mp.exe/iw4x.exe}"'"'"' -- %command%'
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAME="${IW4X32_GAME:-$(dirname "$KIT")}"
DIRECT=0; DRY=0; ARGS=()
for a in "$@"; do
    case "$a" in
        --direct) DIRECT=1 ;;
        --dry-run) DRY=1 ;;
        *) ARGS+=("$a") ;;
    esac
done
run() { if [ "$DRY" = 1 ]; then printf '%q ' "$@"; echo; else "$@"; fi; }
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

# ---- Steam library -----------------------------------------------------------------------------------------------
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
    echo "Or run it right now without Steam's launcher:  bash play-linux.sh --direct"
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
run env STEAM_COMPAT_DATA_PATH="$COMPAT" STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_DIR:-$HOME/.steam/steam}" \
    SteamAppId="$APPID" SteamGameId="$APPID" "$PROTON_DIR/proton" run "$GAME/iw4x.exe" "${ARGS[@]}"
