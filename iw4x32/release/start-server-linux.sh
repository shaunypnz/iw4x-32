#!/bin/sh
# IW4x-32: start a 32-player dedicated server. Kept under its old name - "launcher-linux.sh --server" does the work.
#
#   ./start-server-linux.sh            port 28960
#   ./start-server-linux.sh 28961      another port (one port per server)
#   ./start-server-linux.sh --dry      only check the install and print the command
#
# Settings: the game folder's userraw/server_iw4x32.cfg (made from server/server_iw4x32.cfg on the first start -
# set the server name and an rcon password there). Internet players: forward the port (UDP) to this machine.
# Wine prefix: $WINEPREFIX if set, else ~/.wine-iw4x32-server (kept apart from your desktop Wine).
# Add bots: type  spawnBot 10  in the server console. A normal 18-player IW4x server: launcher-linux.sh --vanilla-server
set -eu
exec bash "$(cd "$(dirname "$0")" && pwd)/launcher-linux.sh" --server "$@"
