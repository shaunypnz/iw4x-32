#!/bin/sh
# Build the IW4x-32 loader (binkw32.dll proxy). Regenerate tables.h first:
#   python3 loader/gen_tables.py --exe-new iw4x.exe.engine32-rNN --dll-new iw4x.dll.stock32X
set -e
cd "$(dirname "$0")"
CC=${CC:-~/xmingw/usr/bin/i686-w64-mingw32-gcc-posix}
mkdir -p build
$CC -O2 -m32 -shared -Wall -Wno-unused-function -o build/binkw32.dll loader.c binkw32.def \
    -ladvapi32 -static-libgcc -Wl,--enable-stdcall-fixup -Wl,--nxcompat
ls -l build/binkw32.dll
