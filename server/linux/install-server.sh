#!/usr/bin/env bash
# IW4x-32 SERVER build install for Linux (Wine). Put the IW4x-32-server folder INSIDE your MW2 / IW4x game folder
# (the folder with iw4x.exe), then run:  bash IW4x-32-server/linux/install-server.sh
# Same steps as "Install IW4x-32.bat": check the official IW4x r5154 files (SHA-256), back them up to
# IW4x-32-server/backup/, install ours, check them. Nothing is downloaded and nothing else is touched.
set -euo pipefail
OFFICIAL_EXE=49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009
OFFICIAL_DLL=82819f1a0c8e3758af8acb8773dc2e2f5cc069202b995e79772a23c9551236cd
OURS_EXE=e692442e7d9a33108aa69472b459b024f4a4fff25fc437fbe996920d2d502424
OURS_DLL=4809ef276852e8c41de027298499546789cb0612abb20b5f13e9b800e2cd6fba
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GAME="$(dirname "$KIT")"
sha() { [ -f "$1" ] && sha256sum "$1" | cut -d' ' -f1 || echo none; }
echo "IW4x-32 SERVER install"
echo "  game folder: $GAME"
[ -f "$GAME/iw4x.exe" ] || { echo "ERROR: no iw4x.exe in $GAME - put the IW4x-32-server folder inside your game folder."; exit 1; }
[ -f "$KIT/files/iw4x.exe" ] && [ -f "$KIT/files/iw4x.dll" ] || { echo "ERROR: IW4x-32-server/files is incomplete - extract the zip again."; exit 1; }
if pgrep -x "iw4x.exe" >/dev/null 2>&1; then echo "ERROR: IW4x is running. Close the game first."; exit 1; fi
if [ "$(sha "$GAME/iw4x.exe")" = "$OURS_EXE" ] && [ "$(sha "$GAME/iw4x.dll")" = "$OURS_DLL" ]; then
    echo "The IW4x-32 server build is already installed."; exit 0
fi
echo "[1/3] Checking your current IW4x files ..."
if [ "$(sha "$GAME/iw4x.exe")" != "$OFFICIAL_EXE" ] || [ "$(sha "$GAME/iw4x.dll")" != "$OFFICIAL_DLL" ]; then
    echo
    echo " STOPPED: your iw4x.exe / iw4x.dll are not the official IW4x r5154 files."
    echo "  - If IW4x was updated since this release, wait for a matching IW4x-32 update."
    echo "  - If you modded them yourself, run the IW4x launcher once to repair, then try again."
    echo " Nothing was changed."
    exit 1
fi
echo "       OK - official IW4x r5154 iw4x.exe and iw4x.dll"
echo "[2/3] Backing up to IW4x-32-server/backup/ ..."
mkdir -p "$KIT/backup"
cp -f "$GAME/iw4x.exe" "$GAME/iw4x.dll" "$KIT/backup/"
echo "[3/3] Installing IW4x-32 ..."
cp -f "$KIT/files/iw4x.exe" "$KIT/files/iw4x.dll" "$GAME/"
if [ "$(sha "$GAME/iw4x.exe")" != "$OURS_EXE" ] || [ "$(sha "$GAME/iw4x.dll")" != "$OURS_DLL" ]; then
    echo "ERROR: the installed files do not match IW4x-32-server/files. Run linux/uninstall-server.sh to restore."; exit 1
fi
echo
echo " Done. The IW4x-32 server build is installed. Next: README.md, section Linux."
echo "  Do NOT run the IW4x launcher/updater: it puts the official 18-player files back."
echo "  Undo any time: bash IW4x-32-server/linux/uninstall-server.sh"
