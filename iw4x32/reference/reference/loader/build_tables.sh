#!/bin/sh
# build_tables.sh ENGINE_VARIANT DLL_VARIANT — regenerate loader/tables.h for a patched build and
# rebuild the loader. The normal builds must already exist in the game folder (patch_engine.py /
# patch_dll.py --dst ...); the --alt-layout builds are made here in a temp dir and diffed.
#   loader/build_tables.sh iw4x.exe.engine32-r16 iw4x.dll.stock32g
set -e
cd "$(dirname "$0")/.."
M="~/Projects/Call of Duty Modern Warfare 2 - modded"
T=$(mktemp -d)
python3 patch_engine.py --src "$M/iw4x.exe.orig32" --dst "$T/alt.exe" --alt-layout > "$T/exe.log"
python3 patch_dll.py --dst "$T/alt.dll" --alt-layout > "$T/dll.log"
# the alt build leaves engine32c/build at the alt base: rebuild it at the normal base
bash engine32c/build.sh > /dev/null
python3 loader/gen_tables.py --exe-new "$1" --exe-alt "$T/alt.exe" --dll-new "$2" --dll-alt "$T/alt.dll"
rm -rf "$T"
loader/build.sh
