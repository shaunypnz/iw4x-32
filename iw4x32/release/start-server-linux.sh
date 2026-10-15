#!/bin/sh
# Start an IW4x-32 dedicated server on Linux (up to 32 players, bots included) - runs iw4x.exe under Wine.
# First run ./install-linux.sh (same as for playing), then:
#
#   ./start-server-linux.sh            port 28960
#   ./start-server-linux.sh 28961      another port (one port per server)
#   ./start-server-linux.sh --dry      only check the install and print the command
#
# Settings: the game folder's userraw/server_iw4x32.cfg (made from server/server_iw4x32.cfg on the first start -
# set the server name and an rcon password there). Internet players: forward the port (UDP) to this machine.
# Wine prefix: $WINEPREFIX if set, else ~/.wine-iw4x32-server (kept apart from your desktop Wine).
# Add bots: type  spawnBot 10  in the server console.
OURS_DLL=f0a247ff84e1307330d43a03c4e8e4f8b8f921a465c6206e0b14a825f736a2d1
KIT=$(cd "$(dirname "$0")" && pwd)
GAME=$(dirname "$KIT")
DRY=
[ "$1" = "--dry" ] && { DRY=1; shift; }
PORT=${1:-28960}
sha() { sha256sum "$1" 2>/dev/null | cut -d' ' -f1; }
[ -f "$GAME/iw4x.exe" ] || { echo "ERROR: no iw4x.exe in $GAME - put the IW4x-32 folder INSIDE your MW2/IW4x game folder."; exit 1; }
if [ "$(sha "$GAME/iw4x.dll")" != "$OURS_DLL" ]; then
    echo "ERROR: IW4x-32 is not installed in $GAME (its iw4x.dll is not the IW4x-32 one). Run ./install-linux.sh first."
    exit 1
fi
mkdir -p "$GAME/userraw"
if [ ! -f "$GAME/userraw/server_iw4x32.cfg" ]; then
    cp "$KIT/server/server_iw4x32.cfg" "$GAME/userraw/server_iw4x32.cfg" || exit 1
    echo "Made userraw/server_iw4x32.cfg - edit it to name your server and set an rcon password."
fi
set -- -dedicated -stdout +set net_port "$PORT" +exec server_iw4x32.cfg +set sv_maxclients 32 +set party_maxplayers 32 \
    +set party_enable 0 +map_rotate
echo "IW4x-32 server"
echo "  game folder: $GAME"
echo "  port:        $PORT (UDP)"
echo "  command:     wine iw4x.exe $*"
[ -n "$DRY" ] && exit 0
command -v wine >/dev/null 2>&1 || { echo "ERROR: wine is not installed (Debian/Ubuntu: sudo apt install wine)."; exit 1; }
cd "$GAME" || exit 1
export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-iw4x32-server}" WINEDEBUG=-all
exec wine iw4x.exe "$@"
