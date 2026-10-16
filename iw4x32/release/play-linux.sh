#!/usr/bin/env bash
# IW4x-32: start the game. Kept under its old name for shortcuts and habits - "launcher-linux.sh" does the work
# (it checks for updates, then starts IW4x-32; --vanilla starts official IW4x, --server starts a server).
#   bash play-linux.sh                  start IW4x-32
#   bash play-linux.sh --vanilla        start vanilla IW4x
#   bash play-linux.sh --dry-run        only print what would be run
#   bash play-linux.sh --no-update      skip the version check
#   bash play-linux.sh --direct         Steam install: run iw4x.exe with the game's Proton, without Steam's launcher
# Steam (Proton) players set this ONCE in Steam -> Modern Warfare 2 - Multiplayer -> Properties -> Launch Options:
#   bash -c 'exec "${@/iw4mp.exe/iw4x.exe}"' -- %command%
# and can then just press Play in Steam. Everything else: bash launcher-linux.sh
set -euo pipefail
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/launcher-linux.sh" --play "$@"
