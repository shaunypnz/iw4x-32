#!/usr/bin/env bash
# Puts your official IW4x iw4x.dll back from IW4x-32/backup/ (made by install-linux.sh or the .bat installer).
# IW4x-32 v2.0 only ever changes iw4x.dll; a backup/iw4x.exe from an older IW4x-32 is restored too.
set -euo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAME="$(dirname "$KIT")"
if pgrep -x "iw4x.exe" >/dev/null 2>&1; then echo "ERROR: close the game first."; exit 1; fi
if [ ! -f "$KIT/backup/iw4x.dll" ]; then
    echo "No backup in IW4x-32/backup/. Run the official IW4x launcher once: it repairs iw4x.exe / iw4x.dll."; exit 1
fi
cp -f "$KIT/backup/iw4x.dll" "$GAME/iw4x.dll"
[ -f "$KIT/backup/iw4x.exe" ] && cp -f "$KIT/backup/iw4x.exe" "$GAME/iw4x.exe"
echo "Restored the official IW4x files. IW4x-32 is uninstalled (you can delete the IW4x-32 folder)."
