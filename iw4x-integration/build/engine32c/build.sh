#!/bin/bash
# Build the engine32c blob: freestanding code/data linked at a fixed VA inside iw4x.exe.
# Outputs: build/engine32c.bin (raw image from BASE), build/engine32c.map (symbol VA list)
set -euo pipefail
cd "$(dirname "$0")"
export PATH=~/xmingw/usr/bin:$PATH
BASE=${E32C_BASE:-0x8800000}
CC=i686-w64-mingw32-gcc-posix
ROLE=${E32C_ROLE:-server}
DEFS=""; [ "$ROLE" = client ] && DEFS="-DE32_CLIENT"
CFLAGS="$DEFS -O2 -m32 -march=i686 -mno-sse -mfpmath=387 -mincoming-stack-boundary=2 -ffreestanding -fno-asynchronous-unwind-tables -fno-pic -fno-stack-protector -fno-builtin -fno-tree-loop-distribute-patterns -Wall -Wextra"
mkdir -p build
OBJS=()
rm -f build/*.o
for s in *.S; do $CC $DEFS -c "$s" -o "build/${s%.S}.o"; OBJS+=("build/${s%.S}.o"); done
for c in *.c; do [ -e "$c" ] || continue; [ "$c" = probe.c ] && continue; [ "$ROLE" = client ] && [ "$c" = antilag.c ] && continue; $CC $CFLAGS -c "$c" -o "build/${c%.c}.o"; OBJS+=("build/${c%.c}.o"); done
i686-w64-mingw32-ld -m i386pe --image-base=0 --section-alignment=0x1000 --file-alignment=0x200 \
    -Ttext=$BASE -e _e32_cl_init_hook --disable-reloc-section -o build/engine32c.exe "${OBJS[@]}"
E32C_BASE=$BASE python3 - <<'PY'
import os, pefile, struct
pe = pefile.PE("build/engine32c.exe")
base = int(os.environ["E32C_BASE"], 16)
secs = [s for s in pe.sections if s.Misc_VirtualSize]
end = max(s.VirtualAddress + s.Misc_VirtualSize for s in secs)   # VirtualAddress is absolute here (image base 0)
blob = bytearray(end - base)
for s in secs:
    data = s.get_data()[:s.Misc_VirtualSize]
    blob[s.VirtualAddress - base: s.VirtualAddress - base + len(data)] = data
    print(f"  {s.Name.rstrip(bytes(1)).decode():8s} {s.VirtualAddress:#x} +{s.Misc_VirtualSize:#x}")
open("build/engine32c.bin", "wb").write(blob)
print(f"  blob {len(blob):#x} bytes @ {base:#x}")
PY
i686-w64-mingw32-nm build/engine32c.exe | awk '$2 ~ /[TtDdBbRr]/ {print $1, $3}' | sort > build/engine32c.map
cat build/engine32c.map
