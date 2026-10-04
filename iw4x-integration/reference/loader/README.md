# IW4x-32 loader

A small DLL that turns a normal **IW4x r5121** install into a 32-player one *in memory*, without
modifying `iw4x.exe` or `iw4x.dll` on disk and without redistributing any Activision or IW4x file.

## How it works

The game imports `binkw32.dll` (Bink video). The loader is installed under that name and forwards all
66 Bink functions to the original, renamed to `binkw32_orig.dll`. Windows (and Wine) run every
imported DLL's start-up code before the game's entry point — and IW4x installs its own hooks only at
that entry point — so the loader can apply the 32-player patches first, exactly as the patched files
built by `patch_engine.py` / `patch_dll.py` would be.

At start-up it:
1. checks the MD5 of `iw4x.exe` and `iw4x.dll` (must be r5121: `9c42ffa4…`, `c7b4cf03…`);
2. checks that **every byte** it is about to replace is the original byte;
3. allocates the extra memory (32-player arrays, injected C code) wherever the OS places it and fixes
   up every reference to it;
4. writes the patches and logs one line to `iw4x32-loader.log` in the game folder.

If anything doesn't match (another IW4x version, an already-patched exe, not enough memory) it changes
**nothing** and the game runs as normal 18-player IW4x; the log says why. Creating an empty file
named `iw4x32-disable` in the game folder turns it off.

## Install (player or server)

1. In the MW2/IW4x folder, rename `binkw32.dll` to `binkw32_orig.dll`.
2. Copy the loader's `binkw32.dll` into the folder.
3. Start `iw4x.exe` directly (not the IW4x launcher/updater while testing).
4. Check `iw4x32-loader.log`: `patched: … 32 players enabled`.

Uninstall: delete `binkw32.dll`, rename `binkw32_orig.dll` back to `binkw32.dll`.

Dedicated servers use the same two files; start with `sv_maxclients 32` and `party_maxplayers 32`
(see `HOSTING_32P.md`).

## Build (Linux, MinGW)

```bash
python3 patch_engine.py --dst "<game>/iw4x.exe.engine32-rNN"     # normal builds, as usual
python3 patch_dll.py    --dst "<game>/iw4x.dll.stock32X"
loader/build_tables.sh iw4x.exe.engine32-rNN iw4x.dll.stock32X    # tables.h + build/binkw32.dll
```
`build_tables.sh` rebuilds both patches with `--alt-layout` (the added blocks moved by fixed deltas)
and `gen_tables.py` diffs the two layouts to find every 4-byte slot that refers to the added memory,
so the loader can place it anywhere. The patch scripts stay the single source of truth.

## Status

- Client: verified live (c20) — an unmodified r5121 client patched itself and played as player 32.
- Server: next test.
- Per IW4x release a new table build is needed (the MD5 check makes an old loader harmless).
