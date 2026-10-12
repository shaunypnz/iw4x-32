# Task (qwen): IW4x-32 engine component - 32 players from iw4x.dll alone (stock iw4x.exe)

This is our fork of iw4x-client (branch iw4x32). The DLL side is done (`Game::MAX_CLIENTS = 32`, see `git log`).
The engine (iw4x.exe = MW2's iw4mp, closed source) is sized for 18 players. Today we ship a binary-patched
iw4x.exe; the goal is that the STOCK iw4x.exe + our iw4x.dll gives 32 players, by patching the engine in memory at
start-up from inside the DLL, like IW4x already does for many engine fixes (src/Components/Modules/*, Utils::Hook).

Everything you need is in `iw4x32/reference/` - read `README.md` there first (it explains every change):
- `engine_patches.json`: all engine changes against the stock r5154 iw4x.exe (base 0x400000): 14 arrays to
  enlarge + 701 operand sites to rewrite, 6 size constants, 85 code patches (27 `dual`: switched at connect time for
  stock 18-player servers), 14 hooks; every entry has `role: client|server`.
- `reference/loader/loader.c` + `gen_tables.py` + `tables.h`: a WORKING in-memory patcher (~240 lines) that applies
  these tables - written for r5121; regenerate the tables for r5154 from engine_patches.json.
- `engine32c/*.c, *.S`: the injected C/asm (layout switch, lag compensation, hook stubs) to port to C++.
- `dll_patches.json` `engine_pointers`: 9 places where IW4x's own code addresses an engine array that moves
  (e.g. `Game::svs_clients`) - point them at the new arrays.

## Deliverables
1. `iw4x32/tools/gen_tables.py`: engine_patches.json -> `src/Components/Modules/IW4x32Tables.hpp` (generated,
   committed). 2. `src/Components/Modules/IW4x32.cpp/.hpp`: a component (register it like the others, see
   `src/Components/Loader.cpp`) that allocates the enlarged arrays, rewrites the operands, applies code patches and
   size constants, installs the hooks, and does the dual (18/32 layout) switch on connect. Port engine32c into it
   (IW4x style: `__declspec(naked)` / `Utils::Hook`). 3. The 9 engine pointers from dll_patches.json.
4. `iw4x32/tools/check_tables.py`: fails unless the generated header holds exactly the entries of
   engine_patches.json (counts per kind and per role, every address). 5. `iw4x32/tools/smoke32.py`: runs our dedicated
   server under Wine with the STOCK exe and THIS build's DLL via the IW4x-32 repo's tools-re/run_server.py
   (`--exe iw4x.exe.orig32 --dll <abs path of build/bin/Win32/Release/iw4x.dll> --maxclients 32 --bots 31
   --duration 240`), and fails unless the server reached the map, 31 bots are in (`status`), and it did not crash.

Build: `bash $HOME/Projects/IW4x-32/tools-re/build_iw4x_fork.sh . Release` (MSVC under Wine, ~4 min; it prepares
this worktree itself). Mark every change with an `// IW4x-32:` comment. Never push.
