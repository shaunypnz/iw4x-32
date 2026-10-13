# AGENTS.md — IW4x-32 fork of iw4x-client

This is upstream IW4x with the IW4x-32 changes on top (branch `iw4x-32`; mark every change `// IW4x-32:`).
- Build: `bash $HOME/Projects/IW4x-32/tools-re/build_iw4x_fork.sh . Release` (MSVC under Wine, ~4 min) ->
  `build/bin/Win32/Release/iw4x.dll`.
- LIVE GAME TEST on the GPU box (real game, real client on its RX 570): `python3
  $HOME/Projects/IW4x-32/tools-re/aiboi_test.py --dll build/bin/Win32/Release/iw4x.dll [--bots 28] [--client]
  [--minutes 5] [--map-change-at 2]` - a 32-slot server on the STOCK iw4x.exe + your DLL, bots, optionally a client,
  optionally a forced map change; prints PASS/FAIL with the numbers and the server console tail. Run it whenever
  a change could affect the game; it waits its turn (one test at a time) and cleans up after itself.
- The engine component (`src/Components/Modules/IW4x32.cpp`) patches the stock exe in memory; its tables are
  generated from `iw4x32/reference/engine_patches.json` (`iw4x32/tools/gen_tables.py`).
- No internal details in any file (IPs, host names, home paths). Never push - the queue does it.
